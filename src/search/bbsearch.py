# -*- coding: utf-8 -*-


import time
import sys
import design
import itertools
import signal

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
* instance of DesignCandidate: basically dictionary mapping collection names to possible shard keys, index keys and collection to denormalize to
* instance of CostModel
* initialDesign (instance of Design)
* upperBound (float; cost of initialDesign)
* timeout (in sec)


2) call solve()
That's it.
'''

class BBSearch ():
    
    # bbsearch object has self.status field, which can have following values:
    # initialized, solving, solved, timed_out, user_terminated
    
    '''
    public methods
    '''
    # main public method. Simply call to get the optimal solution
    def solve(self):
        # set up
        self.leafNodes = 0 # for testing
        self.totalNodes = 0 # for testing
        self.status = "solving"
        #print("===BBSearch Solve===")
        #print " timeout: ", self.timeout
        self.startTime = time.time()
        signal.signal(signal.SIGINT, self.onSigint)
        # set initial bound to infinity
        self.rootNode.solve()
        if self.status is "solving":
            self.status = "solved"
        self.onTerminate()
        return self.bestDesign
       
       
    # traverses the entire tree and returns nodes as list
    # mostly for testing
    # must solve first. Returns only childNodes visited while solving
    def listAllNodes(self):
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
    #SIGINT signal handler
    def onSigint(self, signal, frame):
        print ">> CTRL+C >> Search Aborted by User..."
        self.terminate()
    
    # this event gets called when the search backtracks
    def onBacktrack(self):
        self.totalBacktracks += 1
        self.checkTimeout()
        
    # this event gets called when the algorithm terminates
    def onTerminate(self):
        self.endTime = time.time()
        #self.restoreKeys() # change keys to collection names
        #print "\n===Search ended==="
        #print "  status: ", self.status
        #print "STATISTICS:"
        #print "  time elapsed: ", self.endTime - self.startTime, "s"
        #print "  best cost: ", self.bestCost
        #print "  total backtracks: ", self.totalBacktracks
        #print "  total nodes: ", self.totalNodes
        #print "  leaf nodes: ", self.leafNodes
        #print "BEST SOLUTION:\n", self.bestDesign
        #print "------------------\n"
    
    '''
    class constructor
    args:
    * instance of DesignCandidate: basically dictionary mapping collection names to possible shard keys, index keys and collection to denormalize to
    * instance of CostModel
    * initialDesign (instance of Design)
    * bestCost (float; cost of initialDesign, upper bound)
    * timeout (in sec)
    '''
    def __init__(self, designCandidate, costModel, initialDesign, bestCost, timeout):
        # all nodes have a pointer to the bbsearch object
        # in order to access bounding function, optimial solution and current bound
        self.terminated = False
        # store keys list... used only to translate integer iterators back to real key values...
        self.rootNode = BBNode(design.Design(), self, True, 0) #rootNode: True
        self.designCandidate = designCandidate
        self.costModel = costModel
        self.bestDesign = initialDesign
        self.bestCost = bestCost
        self.totalBacktracks = 0
        self.timeout = timeout
        self.status = "initialized"
        
        
        return
    
## CLASS


'''
helper Classes
'''

'''
Iterators
These iterators help enumerate all possible solutions
used in BBNode getNextChild()
'''
class SimpleKeyIterator:
    def next(self):
        if self.current == len(self.keys):
            raise StopIteration
        else:
            if self.current < 0:
                self.current += 1
                self.lastValue = ""
            else:
                self.current += 1
                self.lastValue = self.keys[self.current - 1]
            return self.lastValue
    
    def rewind(self):
        self.lastValue = None
        self.current = -1
    
    def getLastValue(self):
        # when self.lastValue is None, the iterator has never been called
        # therefore, we must call next() for the first time to pop the first value
        if self.lastValue == None:
            return self.next()
        else:
            return self.lastValue
    
    def __iter__(self):
        return self
    
    def __init__(self, keys):
        self.lastValue = None
        self.keys = keys
        self.current = -1 # no shard key
       
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
        if maxCompoundCount < 0:
            self.maxCompoundCount = len(keys)
        else:
            self.maxCompoundCount = maxCompoundCount







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
    
        #print ("\n ==Node Solve== ")
    
        self.bbsearch.checkTimeout()
        if self.bbsearch.terminated:
            return
            
        
        # do not branch if the solution is complete
        if not self.isLeaf():
        
            self.prepareChildren()
            child = self.getNextChild()
            while child is not None:
                
                #print "\nDEPTH: ", child.depth
                #print child.design
                
                if child.evaluate():
                    self.children.append(child)
                    child.solve()
            
                #child returned --> we backtracked
                self.bbsearch.onBacktrack()
                if self.bbsearch.terminated:
                    return
        
                child = self.getNextChild()
            ## WHILE
        
        # some stats... for testing
        if self.isLeaf():
            self.bbsearch.leafNodes += 1
        self.bbsearch.totalNodes += 1
        
        return
        
    
    # returns None if all children have been enumerated
    def getNextChild(self):
        
        #print ("GET NEXT CHILD")
        
        # use iterators to determine the next assignment for the current collection
        
        # initialize to previous values
        indexes = self.indexIter.getLastValue()
        denorm = self.denormIter.getLastValue()
        
        # SHARD KEY ITERATION
        try:
            shardKey = self.shardIter.next()
        except:
            self.shardIter.rewind()
            shardKey = self.shardIter.next()
            
            # DENORM ITERATION
            try:
                denorm = self.denormIter.next()
            except:
                self.denormIter.rewind()
                denorm = self.denormIter.next()
                
                # INDEX KEYS ITERATION
                try:
                    indexes = self.indexIter.next()
                except:
                    # all combinations exhausted
                    # == all children enumerated
                    return None
        
        #print "APPLYING: ", self.currentCol, "shardKey: ", shardKey, " denorm: ", denorm, " indexes: ", indexes
        
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
        embedded_in = denorm
        # traverse the embedding chain to the end and detect cycles:
        while embedded_in != "":
            # if the end of the "embedded_in" chain is currentCol, it is a CYCLE
            if embedded_in == self.currentCol:
                feasible = False
                break
            if embedded_in in self.design.denorm:
                embedded_in = self.design.denorm[embedded_in]
            else:
                embedded_in = ""
            
        # enforce mutual exclustion of sharding keys...
        # when col1 gets denormalized into col2, they cannot have
        # both assigned a sharding key
        # again, denormalization can be chained... so we have to consider the whole chain
        if (denorm is not "") and (shardKey is not []):
            embedded_in = denorm
            # check all the way to the end of the embedding chain:
            while embedded_in != "":
                # if the encapsulating collection has a shard key, it's a conflict
                if embedded_in in self.design.shardKeys:
                    if self.design.shardKeys[embedded_in] != []:
                        feasible = False
                        break
                if embedded_in in self.design.denorm:
                    embedded_in = self.design.denorm[embedded_in]
                else:
                    embedded_in = ""
                
        # well, this is a very lazy way of doing it :D
        # it's OK so long there are not too many consecutive infeasible nodes,
        # then it could hit the max recursion limit...
        if not feasible:
            #print "FAIL"
            return self.getNextChild()
        
        ### --- end of CONSTRAINTS ---
                
        # make the child
        # inherit the parent assignment plus the new assignment
        child_design = self.design.copy()
        child_design.addCollection(self.currentCol)
        
        for i in indexes :
            child_design.addIndex(self.currentCol, i)
        child_design.addShardKey(self.currentCol, shardKey)
        child_design.setDenormalizationParent(self.currentCol, denorm)
        #child_design.indexes[self.currentCol] = indexes
        #child_design.shardKeys[self.currentCol] = shardKey
        #child_design.denorm[self.currentCol] = denorm
        
        child = BBNode(child_design, self.bbsearch, False, self.depth + 1)
        
        return child
    
        
    def prepareChildren(self):
        # initialize iterators 
        # --> determine which collection is yet to be assigned
        for col in self.bbsearch.designCandidate.collections:
            if col not in self.design.collections:
                self.currentCol = col
                break
        # create the iterators
        self.shardIter = CompoundKeyIterator(self.bbsearch.designCandidate.shardKeys[self.currentCol], SHARD_KEY_MAX_COMPOUND_COUNT)
        self.denormIter = SimpleKeyIterator(self.bbsearch.designCandidate.denorm[self.currentCol])
        self.indexIter = CompoundKeyIterator(self.bbsearch.designCandidate.indexKeys[self.currentCol], INDEX_KEY_MAX_COMPOUND_COUNT)
        
        #print "COL: ", col, "denorm: ", self.bbsearch.designCandidate.denorm[self.currentCol]
        #for f in self.denormIter:
        #    print str(f)
        #self.indexIter.rewind()
        
    # This function determines the lower and upper bound of this node
    # It updates the global lower/upper bound accordingly
    # retrun: True if the node should be explored, False if the node can be discarded
    def evaluate(self):
        #print ".",
        #print self
        sys.stdout.flush()
        # add child only when the solution is admissible
        self.cost = self.bbsearch.costModel.overallCost(self.design)
        #print "EVAL NODE: ", self.design, " bound_lower: ", self.lower_bound, "bound_upper: ", self.upper_bound, "BOUND: ", self.bbsearch.lower_bound
        
        # for leaf nodes (complete solutions):
        # Check against the best value we have seen so far
        # If this node is better, update the optimal solution
        if self.isLeaf():
            if self.cost < self.bbsearch.bestCost:
                self.bbsearch.bestCost = self.cost
                self.bbsearch.bestDesign = self.design.copy()
        
        # A node can be pruned when its cost is greater than the global best_cost
        # So when this function returns False, the node is discarded
        return self.cost <= self.bbsearch.bestCost
        

    # mostly for testing. Recursive.
    def addChildrenToList(self, result):
        for c in self.children:
            result.append(c)
            c.addChildrenToList(result)

    def isLeaf(self):
        return self.design.isComplete(len(self.bbsearch.designCandidate.collections))

    def __str__(self):
        tab="\n"
        for i in range(self.depth):
            tab+="\t"
        s = tab+"--node--"\
        +tab+" cost: " + str(self.cost)\
        +tab+" design: " + str(self.design)\
        +tab+" children: " + str(len(self.children))\
        +tab+" depth: " + str(self.depth)
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
        
        
        return
        

## CLASS