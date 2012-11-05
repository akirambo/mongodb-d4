# -*- coding: utf-8 -*-

import time
import sys
import os
import design
import itertools
import signal
from util import constants
import logging
logging.basicConfig(level = logging.INFO,
format="%(asctime)s [%(filename)s:%(lineno)03d] %(levelname)-5s: %(message)s",
datefmt="%m-%d-%Y %H:%M:%S",
stream = sys.stdout)
LOG = logging.getLogger(__name__)

basedir = os.path.realpath(os.path.dirname(__file__))
sys.path.append(os.path.join(basedir, "../multithreaded"))

from message import *

'''
CONSTANTS & CONFIG
'''
INDEX_KEY_MAX_COMPOUND_COUNT = -1 # index key may consist of any combination of possible indexes
SHARD_KEY_MAX_COMPOUND_COUNT = 3 # composite shard keys may consist at most of 3 keys

## ==============================================
## Branch and Bound search
## ==============================================


'''
Usage:
1) Instantiate BBSearch object. The constructor takes these args:
* instance of DesignCandidates: basically dictionary mapping collection names to possible shard keys, index keys and collection to denormalize to
* instance of CostModel
* initialDesign (instance of Design)
* upperBound (float; cost of initialDesign)
* timeout (in sec)


2) call solve()
That's it.
'''

class BBSearch ():
    """
        bbsearch object has self.status field, which can have following values:
        initialized, solving, solved, timed_out, user_terminated
    """

    def __init__(self, designCandidate, costModel, relaxedDesingn, bestCost, timeout, channel=None, lock=None):
        """
            class constructor
            args:
            * instance of DesignCandidates: basically dictionary mapping collection names to possible shard keys, index keys and collection to denormalize to
            * instance of CostModel
            * initialDesign (instance of Design)
            * bestCost (float; cost of initialDesign, upper bound)
            * timeout (in sec)
        """

        # all nodes have a pointer to the bbsearch object
        # in order to access bounding function, optimial solution and current bound
        self.terminated = False
        # store keys list... used only to translate integer iterators back to real key values...
        self.rootNode = BBNode(relaxedDesingn, self, True, 0) #rootNode: True
        self.designCandidate = designCandidate
        self.costModel = costModel
        self.bestDesign = relaxedDesingn
        self.bestCost = bestCost
        self.totalBacktracks = 0
        self.timeout = timeout
        self.status = "initialized"
        self.usedTime = 0 # track how much time it runs

        self.channel = channel
        self.bestLock = lock
        
        self.debug = LOG.isEnabledFor(logging.DEBUG)
        return

    
    def solve(self):
        """
            main public method. Simply call to get the optimal solution
        """
        # signal.signal(signal.SIGINT, self.onSigint)

        # set up
        self.leafNodes = 0 # for testing
        self.totalNodes = 0 # for testing
        self.status = "solving"
        if self.debug:
            LOG.debug("===BBSearch Solve===")
            LOG.debug(" timeout: %d", self.timeout)
        self.startTime = time.time()

        # set initial bound to infinity
        self.rootNode.solve()
        
        if self.status is "solving":
            self.status = "solved"

        self.onTerminate()

        self.usedTime = time.time() - self.startTime
        
        return self.bestDesign

    def listAllNodes(self):
        """
            traverses the entire tree and returns nodes as list
            mostly for testing
            must solve first. Returns only childNodes visited while solving
        """
        result = [self.rootNode]
        self.rootNode.addChildrenToList(result)
        return result
        
    # only called externally. This stops the search.
    def terminate(self):
        self.status = "user_terminated"
        self.terminated = True
        
    '''
    private methods
    '''
    
    def checkTimeout(self):
        if time.time() - self.startTime > self.timeout:
            self.status = "timed_out"
            self.terminated = True
    
    '''
    Events
    '''
    def onSigint(self, signal, frame):
        """SIGINT signal handler"""
        LOG.warn(">> CTRL+C >> Search Aborted by User...")
        self.terminate()
    
    # this event gets called when the search backtracks
    def onBacktrack(self):
        self.totalBacktracks += 1
        self.checkTimeout()
        
    def onTerminate(self):
        """this event gets called when the algorithm terminates"""
        self.endTime = time.time()
        #self.restoreKeys() # change keys to collection names
        if self.debug:
            LOG.debug("===Search ended===")
            LOG.debug("  status: %s", self.status)
            LOG.debug("STATISTICS:")
            LOG.debug("  time elapsed: %d", (self.endTime - self.startTime))
            LOG.debug("  best cost: %s", self.bestCost)
            LOG.debug("  total backtracks: %d", self.totalBacktracks)
            LOG.debug("  total nodes: %d", self.totalNodes)
            LOG.debug("  leaf nodes: %d", self.leafNodes)
            LOG.debug("BEST SOLUTION:\n%s", self.bestDesign)
            LOG.debug("------------------\n")
## CLASS


'''
helper Classes
'''

'''
Iterators
These iterators help enumerate all possible solutions
used in BBNode getNextChild()
NOTE: This will always return None as the first value
'''
class SimpleKeyIterator:
    def next(self):
        if self.current == len(self.keys):
            raise StopIteration
        else:
            if self.current < 0:
                self.current += 1
                self.lastValue = None
            else:
                self.current += 1
                self.lastValue = self.keys[self.current - 1]
            self.first = False
            return self.lastValue
    
    def rewind(self):
        self.first = True
        self.lastValue = None
        self.current = -1
    
    def getLastValue(self):
        # when first is set to true, then the iterator has never been called
        # therefore, we must call next() for the first time to pop the first value
        if self.first:
            return self.next()
        else:
            return self.lastValue
    
    def __iter__(self):
        return self
    
    def __init__(self, keys):
        self.first = True
        self.lastValue = None
        self.keys = keys
        self.current = -1
       
# this one is a bit more complicated:
# we have to enumerate all combinations of all sizes from the list of index keys
class CompoundKeyIterator: 
    def next(self):
        if self.currentSize > self.maxCompoundCount:
            raise StopIteration
        else:
            result = None
            if self.currentSize == 0:
                self.currentSize = 1
                result = []
            else:
                if self.currentIterator is None:
                    self.currentIterator = itertools.combinations(self.keys, self.currentSize)
                try:
                    result = self.currentIterator.next()
                    if result in self.invalidCombinations:
                        return None
                except:
                    self.currentSize += 1
                    self.currentIterator = None
                    result = self.next()
            self.lastValue = result
            return result
    
    def rewind(self):
        self.lastValue = None
        self.currentSize = 0
        self.currentIterator = None
    
    def getLastValue(self):
        # when self.lastValue is None, the iterator has never been called
        # therefore, we must call next() for the first time to pop the first value
        if self.lastValue == None:
            return self.next()
        else:
            return self.lastValue
    
    def __iter__(self):
        return self
    
    def __generate_invalid_combinations__(self, keys, maxCompoundCount):
        """
            We don't want to evaluate combinations like ((f0), (f0, f1)) or ((f0, f1), (f0, f1, f2))
            But we want to evalute them seperately
        """
        invalid_combination = set()
        marker = None
        for i in xrange(2, maxCompoundCount + 1):
            if i > constants.MAX_INDEX_SIZE: break
            iterator = itertools.combinations(keys, i)
            try:
                while True:
                    result = iterator.next()
                    for keys0 in result:
                        for keys1 in result:
                            marker = True
                            if keys1 != keys0:
                                counter = 0
                                while counter < len(keys0):
                                    if keys0[counter] != keys1[counter]:
                                        marker = False
                                        break
                                    counter += 1
                                    ## IF
                                ## WHILE
                                if marker:
                                    invalid_combination.add(result)
                                    break
                           ## IF
                        if marker:
                            break
                       ## IF
                    ## FOR
                ## WHILE
            except StopIteration:
                pass
        ## FOR
        
        return invalid_combination
    ## DEF
    '''
    maxCompoundCount - maximum number of elements in the compound key.
    anything < 0 means "unlimited"
    '''
    def __init__(self, keys, maxCompoundCount):
        # blow up all possible combinations of index keys
        self.lastValue = None
        self.currentSize = 0
        self.keys = keys
        self.currentIterator = None
        self.invalidCombinations = None
        if maxCompoundCount < 0:
            self.maxCompoundCount = constants.MAX_INDEX_SIZE
        else:
            self.maxCompoundCount = maxCompoundCount
        
        self.invalidCombinations = self.__generate_invalid_combinations__(self.keys, self.maxCompoundCount)
## CLASS

## ==============================================
## BBNode: main building block of the BBSearch tree
## ==============================================
'''
BBNode - basic building block of the BBSearch tree
This class is basically a wrapper around Design
'''
class BBNode():
   # this is depth first search for now
    def solve(self):

        LOG.debug(("\n ==Node Solve== "))
    
        self.bbsearch.checkTimeout()
        if self.bbsearch.terminated:
            return

        # do not branch if the solution is complete
        if not self.isLeaf():

            self.prepareChildren()
            child = self.getNextChild()
            while child is not None:
                if self.debug:
                    LOG.debug("DEPTH: %d", child.depth)
                    LOG.debug(child.design.data)

                if child.evaluate():
                    self.children.append(child)
                    child.solve()
            
                #child returned --> we backtracked
                self.bbsearch.onBacktrack()
                if self.bbsearch.terminated:
                    return
        
                child = None
                try:
                    child = self.getNextChild()
                except StopIteration:
                    pass
            ## WHILE
        
        # some stats... for testing
        if self.isLeaf():
            self.bbsearch.leafNodes += 1
        self.bbsearch.totalNodes += 1
        
        return
        
    
    # returns None if all children have been enumerated
    def getNextChild(self):
        if self.debug:
            LOG.debug("GET NEXT CHILD")
        
        # use iterators to determine the next assignment for the current collection
        
        # initialize to previous values
        shardKey = self.shardIter.getLastValue()
        indexes = self.indexIter.getLastValue()
        
        # DENORM KEY ITERATION
        try:
            denorm = self.denormIter.next()
        except:
            self.denormIter.rewind()
            denorm = self.denormIter.next()
            
            # ShARDKEY ITERATION
            try:
                shardKey = None
                while shardKey == None:
                    shardKey = self.shardIter.next()
            except:
                self.shardIter.rewind()
                shardKey = self.shardIter.next()
                
                # INDEX KEYS ITERATION
                try:
                    indexes = None
                    while indexes == None:
                        indexes = self.indexIter.next()
                except:
                    # all combinations exhausted
                    # == all children enumerated
                    return None
        if self.debug:
            LOG.debug("APPLYING: %s -> shardKey:%s / denorm:%s / indexes:%s", \
                      self.currentCol, shardKey, denorm, indexes)
                
        # well, this is a very lazy way of doing it :D
        # it's OK so long there are not too many consecutive infeasible nodes,
        # then it could hit the max recursion limit...
        if not self.__isFeasible__(denorm, shardKey):
            LOG.warn("FAIL")
            return self.getNextChild()
            
        ### --- end of CONSTRAINTS ---
        # make the child
        # inherit the parent assignment plus the new assignment
        child_design = self.design.copy()
        if child_design.isRelaxed(self.currentCol):
            child_design.recover(self.currentCol)
        
        for i in indexes:
            child_design.addIndex(self.currentCol, i)
        child_design.addShardKey(self.currentCol, shardKey)
        child_design.setDenormalizationParent(self.currentCol, denorm)
        child = BBNode(child_design, self.bbsearch, False, self.depth + 1)
        
        return child

    def __isFeasible__(self, denorm, shardKey):
        ###             CONSTRAINTS     
        ### --- Solution Feasibility Check ---
        
        # IMPORTANT
        # This might be a stupid way of doing it, but let's go with it for now
        # --> check feasibility of this partial solution:
        #   * embedded collections should not have a sharding key
        #       -note: actually, the sharding key could be picked from the embedded collection,
        #       but in that case we must ensure the sharding key is not assigned on the enclosing collection...
        #   * NO CIRCULAR EMBEDDING
        
        feasible = True
        # NO CIRCULAR EMBEDDING - this checks against "embedding in itself" as well
        denorm_parent = denorm
        # traverse the embedding chain to the end and detect cycles:
        while denorm_parent:
            # if the end of the "embedded_in" chain is currentCol, it is a CYCLE
            if denorm_parent == self.currentCol:
                feasible = False
                break
            denorm_parent = self.design.getDenormalizationParent(denorm_parent)
            
        # Empty denormalization collection?
        if not denorm is None and len(denorm) == 0:
            LOG.warn("Invalid denormalization candidate '%s' for collection %s", denorm, self.currentCol)
            feasible = False
            
        # enforce mutual exclustion of sharding keys...
        # when col1 gets denormalized into col2, they cannot have
        # both assigned a sharding key
        # again, denormalization can be chained... so we have to consider the whole chain
        if feasible and not denorm is None and len(shardKey) != 0:
            denorm_parent = denorm
            # check all the way to the end of the embedding chain:
            while denorm_parent:
                # if the encapsulating collection has a shard key, it's a conflict
                if denorm_parent in self.design.data:
                    if self.design.getShardKeys(denorm_parent) is not None and len(self.design.getShardKeys(denorm_parent)) != 0:
                        feasible = False
                        break
                denorm_parent = self.design.getDenormalizationParent(denorm_parent)
        
        return feasible
    
    def prepareChildren(self):
        # initialize iterators 
        # --> determine which collection is yet to be assigned
        for col_name in self.bbsearch.designCandidate.collections:
            if self.design.isRelaxed(col_name):
                self.currentCol = col_name
                break
        # create the iterators
        self.shardIter = CompoundKeyIterator(self.bbsearch.designCandidate.shardKeys[self.currentCol], SHARD_KEY_MAX_COMPOUND_COUNT)
        self.denormIter = SimpleKeyIterator(self.bbsearch.designCandidate.denorm[self.currentCol])
        self.indexIter = CompoundKeyIterator(self.bbsearch.designCandidate.indexKeys[self.currentCol], INDEX_KEY_MAX_COMPOUND_COUNT)
        
        if self.debug:
            LOG.debug("COL: %s / denorm: %s", col_name, self.bbsearch.designCandidate.denorm[self.currentCol])
        #for f in self.denormIter:
        #    print str(f)
        #self.indexIter.rewind()
        
    # This function determines the lower and upper bound of this node
    # It updates the global lower/upper bound accordingly
    # retrun: True if the node should be explored, False if the node can be discarded
    def evaluate(self):
        if self.debug:
            LOG.debug(".",)
            LOG.debug(self)
        # add child only when the solution is admissible
        LOG.info("Evaluated design: \n%s", self.design)
        self.cost = self.bbsearch.costModel.overallCost(self.design)
#        LOG.debug("EVAL NODE: %s / bound_lower:%f / bound_upper:%f / BOUND:%f", \
#                  self.design, self.lower_bound, self.upper_bound, self.bbsearch.lower_bound)

        # for leaf nodes (complete solutions):
        # Check against the best value we have seen so far
        # If this node is better, update the optimal solution
        self.bbsearch.bestLock.acquire()
        if self.isLeaf():
            if self.cost < self.bbsearch.bestCost:
                self.bbsearch.bestCost = self.cost
                self.bbsearch.bestDesign = self.design.copy()
                LOG.info("Best Cost is updated from %s to %s", self.bbsearch.bestCost, self.cost)
                LOG.info("New Best design: \n%s", self.design)
                LOG.info("Sending update to coorinator...")
                sendMessage(MSG_NEW_BEST_COST, (self.bbsearch.bestCost, self.bbsearch.bestDesign), self.bbsearch.channel)
                
        # A node can be pruned when its cost is greater than the global best_cost
        # So when this function returns False, the node is discarded
        isCostBetter = (self.cost <= self.bbsearch.bestCost)
        self.bbsearch.bestLock.release()
        return isCostBetter
        

    # mostly for testing. Recursive.
    def addChildrenToList(self, result):
        for c in self.children:
            result.append(c)
            c.addChildrenToList(result)

    def isLeaf(self):
        return self.design.isComplete()

    def __str__(self):
        tab = "   "*self.depth
        
        designStr = ""
        for line in str(self.design).split("\n"):
            designStr += "\n" + tab + "  |" + line
        
        s = tab + "--node--\n" + \
            tab + " cost: " + str(self.cost) + "\n" + \
            tab + " children: " + str(len(self.children)) + "\n" + \
            tab + " depth: " + str(self.depth) + "\n" + \
            tab + " design: " + designStr
        return s

    '''
    class constructor
     input:
     d - instance of Design
     bb - instance of BBSearch
     isroot - True/False
     depth 
    '''
    def __init__(self, d, bb, isroot, depth):
        self.cost = None
        self.depth = depth
        self.design = d
        self.bbsearch = bb
        self.children = [] # list of BBNode
        self.debug = LOG.isEnabledFor(logging.DEBUG)
        return
        

## CLASS