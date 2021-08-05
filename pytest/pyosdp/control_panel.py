#
#  Copyright (c) 2021 Siddharth Chandrasekaran <sidcha.dev@gmail.com>
#
#  SPDX-License-Identifier: Apache-2.0
#

import os
import tempfile
import osdp
import time
import queue
import threading

from .helpers import PDInfo
from .constants import LogLevel

class ControlPanel():
    def __init__(self, pd_info_list, log_level: LogLevel=LogLevel.Info,
                 master_key: bytes=None):
        self.pd_addr = []
        info_list = []
        self.num_pds = len(pd_info_list)
        for pd_info in pd_info_list:
            self.pd_addr.append(pd_info.address)
            info_list.append(pd_info.get())
        self.event_queue = [ queue.Queue() for i in self.pd_addr ]
        if master_key:
            self.ctx = osdp.ControlPanel(info_list, master_key=master_key)
        else:
            self.ctx = osdp.ControlPanel(info_list)
        self.ctx.set_event_callback(self.event_handler)
        self.ctx.set_loglevel(log_level)
        self.event = threading.Event()
        self.lock = threading.Lock()
        args = (self.event, self.lock, self.ctx,)
        self.thread = threading.Thread(name='cp', target=self.refresh, args=args)

    @staticmethod
    def refresh(event, lock, ctx):
        while not event.is_set():
            lock.acquire()
            ctx.refresh()
            lock.release()
            time.sleep(0.020) #sleep for 20ms

    def event_handler(self, address, event):
        pd = self.pd_addr.index(address)
        self.event_queue[pd].put(address, event)

    def get_num_online(self):
        online = 0
        for i in range(len(self.pd_addr)):
            self.lock.acquire()
            if self.ctx.is_online(i):
                online += 1
            self.lock.release()
        return online

    def get_num_sc_active(self):
        sc_active = 0
        self.lock.acquire()
        for i in range(len(self.pd_addr)):
            if self.ctx.sc_active(i):
                sc_active += 1
        self.lock.release()
        return sc_active

    def sc_status(self):
        self.lock.acquire()
        mask = self.ctx.sc_status()
        self.lock.release()
        return mask

    def is_sc_active(self, address):
        pd = self.pd_addr.index(address)
        mask = self.sc_status()
        return mask & (1 << pd)

    def is_online(self, address):
        pd = self.pd_addr.index(address)
        self.lock.acquire()
        ret = self.ctx.is_online(pd)
        self.lock.release()
        return ret

    def send_command(self, address, cmd):
        pd = self.pd_addr.index(address)
        self.lock.acquire()
        ret = self.ctx.send_command(pd, cmd)
        self.lock.release()
        return ret

    def register_file_ops(self, address, fops):
        pd = self.pd_addr.index(address)
        self.lock.acquire()
        ret = self.ctx.register_file_ops(pd, fops)
        self.lock.release()
        return ret

    def get_file_tx_status(self, address):
        pd = self.pd_addr.index(address)
        self.lock.acquire()
        ret = self.ctx.get_file_tx_status(pd)
        self.lock.release()
        return ret

    def start(self):
        if not self.thread:
            return False
        self.thread.start()

    def stop(self):
        while self.thread and self.thread.is_alive():
            self.event.set()
            self.thread.join(2)
            if not self.thread.is_alive():
                return True
        return False

    def online_wait_all(self, timeout=10):
        count = 10
        res = False
        while count < timeout * 2:
            time.sleep(0.5)
            if self.get_num_online() == len(self.pd_addr):
                res = True
                break
            count += 1
        return res

    def online_wait(self, address, timeout=5):
        count = 10
        res = False
        while count < timeout * 2:
            time.sleep(0.5)
            if self.is_online(address):
                res = True
                break
            count += 1
        return res

    def sc_wait(self, address, timeout=5):
        count = 0
        res = False
        while count < timeout * 2:
            time.sleep(0.5)
            if self.is_sc_active(address):
                res = True
                break
            count += 1
        return res

    def sc_wait_all(self, timeout=5):
        count = 0
        res = False
        all_pd_mask = (1 << self.num_pds) - 1
        while count < timeout * 2:
            time.sleep(0.5)
            if self.sc_status() == all_pd_mask:
                res = True
                break
            count += 1
        return res

    def teardown(self):
        self.stop()
        self.ctx = None