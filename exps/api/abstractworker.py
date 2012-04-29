# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------
# Copyright (C) 2012
# Yang Lu - http://www.cs.brown.edu/~yanglu/
# Andy Pavlo - http://www.cs.brown.edu/~pavlo/
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
import time
import logging
import traceback
import pymongo
from pprint import pformat

# Designer
import search

# Benchmark API
from .results import *
from .message import *

LOG = logging.getLogger(__name__)

class AbstractWorker:
    '''Abstract Benchmark Worker'''
    def __init__(self):
        ''' All subclass constructor should not take any argument. You can do more initializing work in initializing method '''
        self.config = None
        self.name = None
        self.id = None
        self.stop_on_error = False
        pass
    ## DEF
    
    def getWorkerId(self):
        """Return the unique identifier for this worker instance"""
        return self.id
    
    def getBenchmarkName(self):
        return self.name
    
    def init(self, config, channel):
        '''Work Initialization. You always must send a INIT_COMPLETED message back'''
        self.config = config
        self.name = config['default']['name']
        self.id = config['default']['id']
        self.stop_on_error = config['default']['stop_on_error']
        self.debug = config['default']['debug']
        
        LOG.info("Initializing %s Worker [clientId=%d]" % (self.name.upper(), self.id))
        if self.debug:
            LOG.debug("%s Configuration:\n%s" % (self.name.upper(), pformat(self.config[self.name])))
        
        ## ----------------------------------------------
        ## DATABASE DESIGN
        ## ----------------------------------------------
        self.design = None
        if config['default']['design']:
            if self.debug:
                LOG.debug("Instantiating design from JSON")
            initalD, self.design = search.utilmethods.fromJSON(config['default']['design'])
            if self.debug:
                LOG.debug("Design:\n%s" % self.design)
        
        ## ----------------------------------------------
        ## TARGET CONNECTION
        ## ----------------------------------------------
        self.conn = None
        targetHost = config['default']['host']
        targetPort = config['default']['port']
        if self.debug:
            LOG.debug("Connecting MongoDB database at %s:%d" % (targetHost, targetPort))
        try:
            self.conn = pymongo.Connection(targetHost, targetPort)
        except:
            LOG.error("Failed to connect to target MongoDB at %s:%s" % (targetHost, targetPort))
            raise
        assert self.conn
        
        self.initImpl(config)
        sendMessage(MSG_INIT_COMPLETED, None, channel)
    ## DEF
    
    def initImpl(self, config):
        raise NotImplementedError("%s does not implement initImpl" % (self.name))
        
    def load(self, config, channel, msg):
        '''Perform actual loading. We will always send back LOAD_COMPLETED message'''
        LOG.info("Invoking %s Loader" % self.name)
        self.loadImpl(config, channel, msg)
        sendMessage(MSG_LOAD_COMPLETED, None, channel)
        pass
    ## DEF
    
    def loadImpl(self, config, channel, msg):
        raise NotImplementedError("%s does not implement loadImpl" % (self.name))
        
    def execute(self, config, channel, msg):
        ''' Actual execution. You might want to send a EXECUTE_COMPLETED message back with the loading time'''
        config['default']['execute'] = True
        config['default']['reset'] = False
        
        r = Results()
        assert r
        LOG.info("Executing benchmark for %d seconds" % config['default']['duration'])
        start = r.startBenchmark()
        debug = LOG.isEnabledFor(logging.DEBUG)

        while (time.time() - start) <= config['default']['duration']:
            txn, params = self.next(config)
            txn_id = r.startTransaction(txn)
            
            logging.debug("Executing '%s' transaction" % txn)
            try:
                val = self.executeImpl(config, txn, params)
            except KeyboardInterrupt:
                return -1
            except (Exception, AssertionError), ex:
                logging.warn("Failed to execute Transaction '%s': %s" % (txn, ex))
                if debug: traceback.print_exc(file=sys.stdout)
                if self.stop_on_error: raise
                r.abortTransaction(txn_id)
                continue

            #if debug: logging.debug("%s\nParameters:\n%s\nResult:\n%s" % (txn, pformat(params), pformat(val)))
            
            r.stopTransaction(txn_id)
        ## WHILE
            
        r.stopBenchmark()
        sendMessage(MSG_EXECUTE_COMPLETED, r, channel)
    ## DEF
        
    def next(self, config):
        raise NotImplementedError("%s does not implement next" % (self.name))
        
    def executeImpl(self, config, txn, params):
        raise NotImplementedError("%s does not implement executeImpl" % (self.name))
        
    def moreProcessing(config, channel, msg):
        '''hook'''
        return None
## CLASS

