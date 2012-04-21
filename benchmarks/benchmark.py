#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------
# Copyright (C) 2012
# Yang Lu + Andy Pavlo
# http://www.cs.brown.edu/~pavlo/
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
# IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
# -----------------------------------------------------------------------

import sys
import os
import string
import re
import argparse
import glob
import execnet
import msgprocessor
import logging
from message import *
from ConfigParser import SafeConfigParser
from pprint import pprint,pformat

logging.basicConfig(level = logging.INFO,
                    format="%(asctime)s [%(funcName)s:%(lineno)03d] %(levelname)-5s: %(message)s",
                    datefmt="%m-%d-%Y %H:%M:%S",
                    stream = sys.stdout)

## ==============================================
## Benchmark Invocation
## ==============================================
class Benchmark:
    '''main class'''
    def __init__(self, args):
        self._args = args
        self._config = self.loadConfig()
        self._channels = self.createChannels()
        self._coordinator = self.createCoordinator()
        
    def loadConfig(self):
        '''Load configuration file'''
        assert 'config' in self._args
        assert self._args['config'] != None
        
        cparser = SafeConfigParser()
        cparser.read(os.path.realpath(self._args['config'].name))
        config = dict(cparser.items('configuration'))
        logging.debug("Configuration File:\n%s" % config)
        return config
        
    def createChannels(self):
        '''Create a list of channels used for communication between coordinator and worker'''
        channels=[]
        assert self._config['clients']!=''
        clients = re.split(r"\s+",str(self._config['clients']))
        logging.info(clients)
        ##Create ssh channels to client nodes
        for node in clients:
            cmd = 'ssh='+ node
            cmd += r"//chdir="
            cmd += self._config['path']
            logging.debug(cmd)
            logging.debug(self._config['clientprocs'])
            for i in range(int(self._config['clientprocs'])):
                gw = execnet.makegateway(cmd)
                ch = gw.remote_exec(msgprocessor)
                channels.append(ch)
        logging.info(channels)
        return channels
        
    def createCoordinator(self):
        '''Coordinator factory method.'''
        benchmark = self._config['benchmark']
        fullName= benchmark.title()+"Coordinator"
        mod = __import__('%s.%s' %(benchmark.lower(),fullName.lower()), globals(), locals(), [fullName])
        klass = getattr(mod, fullName)
        return klass()
    
    def runBenchmark(self):
        '''A template method for all benchmarks'''
        for ch in self._channels:
            sendMessage(CONFIG,self._config,ch)
            
        self._coordinator.initialize(self._config,self._channels)       
        if not self._args['no_load']:
            self._coordinator.distributeLoading(self._config,self._channels)            
        if not self._args['no_execute']:
            self._coordinator.distributeExecution(self._config,self._channels)    
        self._coordinator.showResult(self._config,self._channels)        
        self._coordinator.moreProcessing(self._config,self._channels)
        
## ==============================================
## getBenchmarks
## ==============================================
def getBenchmarks():
    benchmarks = [ ]
    for f in glob.glob("./benchmarks/*"):
        if os.path.isdir(f): benchmarks.append(os.path.basename(f).strip())
    return (benchmarks)
## DEF

## ==============================================
## MAIN
## ==============================================
if __name__=='__main__':
    #Simplified args
    aparser = argparse.ArgumentParser(description='MongoDB Benchmark Framework')
    aparser.add_argument('benchmark', choices=getBenchmarks(),
                         help='Target benchmark')
    aparser.add_argument('--config', type = file,
                         help='Path to benchmark configuration file')
    aparser.add_argument('--reset', action='store_true',
                         help='Instruct the driver to reset the contents of the database')
    aparser.add_argument('--scalefactor', default=1, type=float, metavar='SF',
                         help='Benchmark scale factor')
    aparser.add_argument('--clientprocs', default=1, type=int, metavar='N',
                         help='Number of processes on each client node.')
                         
    aparser.add_argument('--stop-on-error', action='store_true',
                         help='Stop the transaction execution when the driver throws an exception.')
    aparser.add_argument('--no-load', action='store_true',
                         help='Disable loading the benchmark data')
    aparser.add_argument('--no-execute', action='store_true',
                         help='Disable executing the benchmark workload')
    aparser.add_argument('--print-config', action='store_true',
                         help='Print out the default configuration file for the benchmark and exit')
    aparser.add_argument('--debug', action='store_true',
                         help='Enable debug log messages')                       
    args = vars(aparser.parse_args())
    
    if args['debug']: logging.getLogger().setLevel(logging.DEBUG)
    
    logging.debug("Command Options:\n%s" % args)
    ben = Benchmark(args)
    ben.runBenchmark()
## MAIN
    
 
