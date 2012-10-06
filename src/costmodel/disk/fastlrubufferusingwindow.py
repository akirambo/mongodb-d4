"""
    This is lrubuffer is intended to be faster version of the existing lrubuffer.
    In this version, the buffer will be implemented as a dictionary which maps the current key
    to its predecessor's and successor's key:

    HEAD: <buffer-tuple>
    TAIL: <buffer-tuple>
    BUFFER: { <buffer-tuple>: [ <prev-buffer-value>, <next-buffer-value>, <size> ] }

    The HEAD and TAIL are used to pop and push entries out and into the buffer based on LRU rules
    """
import logging
import random
from pprint import pformat
from util import constants

# constants
PREV_BUFFER_ENTRY = 0
NEXT_BUFFER_ENTRY = 1

DOC_TYPE_INDEX = 0
DOC_TYPE_COLLECTION = 1

BUFFER = 0
HEAD = 1
TAIL = 2

LOG = logging.getLogger(__name__)

class FastLRUBufferWithWindow:

    def __init__(self, collections, window_size, preload=constants.DEFAULT_LRU_PRELOAD):

        self.debug = LOG.isEnabledFor(logging.DEBUG)
        self.preload = preload

        self.collections = collections
        
        self.buffer = { }
        self.head = None # the top element in the buffer
        self.tail = None # the bottom element in the buffer

        # This is the total amount of slots available in this buffer (integer)
        self.window_size = window_size
        # This is the amount of space that is unallocated in this buffer (bytes)
        self.free_slots = window_size
        self.evicted = 0
        self.refreshed = 0

        self.address_size = constants.DEFAULT_ADDRESS_SIZE # FIXME
        ## DEF

    def reset(self):
        """
            Reset the internal buffer and "free" all of its used memory
        """
        self.free_slots = self.window_size
        self.buffer = { }
        self.evicted = 0
        self.refreshed = 0
        self.head = None
        self.tail = None
    ## DEF

    def initialize(self, design, delta, cache):
        """
            Add the given collection to our buffer.
            This will automatically initialize any indexes for the collection as well.
        """
        self.reset()
        
        if cache:
          self.buffer = self.__clone_dictionary__(cache.buffer)
          self.head = self.__clone_buffer_value__(cache.head)
          self.tail = self.__clone_buffer_value__(cache.tail)
          self.evicted = cache.evicted
          self.refreshed = cache.refreshed
          self.free_slots = cache.free_slots
        else:
            self.__init_collections__(design, delta)
          
        return self

    def __clone_dictionary__(self, source):
        target = { }

        for key, value in source.iteritems():
            target[key] = value

        return target

    def __clone_buffer_value__(self, source): # clone the "link" in the doubly linked-list
        if source is None:
            return None
        
        newValue = [None, None, None]
        newValue[PREV_BUFFER_ENTRY] = source[PREV_BUFFER_ENTRY][:] if source[PREV_BUFFER_ENTRY] else None
        newValue[NEXT_BUFFER_ENTRY] = source[NEXT_BUFFER_ENTRY][:] if source[NEXT_BUFFER_ENTRY] else None

        return newValue
    def getDocumentFromIndex(self, col_name, indexKeys, documentId):
        """
            Get the documents from the given index
            Returns the number of page hits incurred to read these documents.
        """
#        assert size > 0,"Missing index size for %s -> '%s'\n%s" % (col_name, indexKeys, pformat(self.index_sizes))
        return self.getDocument(DOC_TYPE_INDEX, col_name, indexKeys, documentId, True)
        ## DEF

    def getDocumentFromCollection(self, col_name, documentId):
 #      assert size > 0, "Missing collection size for '%s'" % col_name
        return self.getDocument(DOC_TYPE_COLLECTION, col_name, col_name, documentId, False)
    ## DEF

    def getDocument(self, typeId, col_name, keys, documentId, isFromIndex):

        # Pre-hashing the tuple greatly improves the performance of this
        # method because we don't need to keep redoing it when we update
        buffer_tuple = (documentId, col_name, typeId)
        buffer_tuple_index = []
        if isFromIndex:
            for key in keys:
                buffer_tuple_index.append((documentId, key, typeId))

        offset = self.buffer.get(buffer_tuple, None)

        # The tuple is in our buffer, so we don't need to fetch anything from disk
        # We will need to push the tuple back on to the end of our buffer list
        if offset:
            self.__update__(buffer_tuple)
            self.refreshed += 1
            return 0 # page_hits

        # It's not in the buffer for this index, so we're going to have
        # go fetch it from disk. Check whether we can just fetch
        # the page in or whether we will need to write out a dirty page right now
        # NOTE: We actually don't know whether the page is dirty. If it wasn't then
        #       OS would just discard it rather than write it back to disk. Figuring
        #       that out would be too expensive for this estimate, since we don't
        #       actually know how many documents are in that page that it needs to write
        else:
#            assert not buffer_tuple in self.buffer, "Duplicate entry '%s'" % buffer_tuple
#            assert size < self.buffer_size
            tuple_page_hits = self.__push__(buffer_tuple)
            if isFromIndex:
                index_page_hits = 0
                for index_tuple in buffer_tuple_index:
                    index_page_hits += self.__push__(index_tuple)
                return tuple_page_hits + index_page_hits
            else:
                return self.__push__(buffer_tuple)
        ## DEF

    def __init_collections__(self, design, delta):

        for col_name in design.getCollections():
            if not self.preload: break

            col_info = self.collections[col_name]
            indexes = design.getIndexes(col_name) 

            # How much space are they allow to have in the initial configuration
            col_remaining = int(self.window_size * (delta * col_info['workload_percent']))
            if self.debug:
                LOG.debug("%s Pre-load Percentage: %.1f%% [bytes=%d]",
                    col_name, (delta * col_info['workload_percent'])*100, col_remaining)

            ctr = 0
            rng = random.Random()
            rng.seed(col_name)
            while col_remaining > 0 and self.evicted == 0:
                documentId = rng.random()
                if len(indexes) == 0:
                    self.getDocumentFromCollection(col_name, documentId)
                else:
                    self.getDocumentFromIndex(col_name, indexes, documentId)
                col_remaining -= 1
                ctr += 1
            ## WHILE
            if self.debug:
                LOG.debug("Pre-loaded %d documents for %s - %s", ctr, col_name, self)
                ## FOR

        if self.debug and self.preload:
            LOG.debug("Total # of Pre-loaded Documents: %d", len(self.buffer.keys()))
        ## DEF

    ##  -----------------------------------------------------------------------
    ##  LRU operations
    ##  -----------------------------------------------------------------------

    def __pop__(self):
        """
            pop out the least recent used buffer_tuple from the buffer
        """
        self.__remove__(self.head)
        self.evicted += 1
    ## DEF

    def __update__(self, buffer_tuple):
        """
            update the given buffer_tuple in the buffer
            Basically, it just puts the given buffer_tuple at the end of the queue
        """
        if buffer_tuple == self.tail:
            return

        isRemoved, value = self.__remove__(buffer_tuple)
        if isRemoved:
            self.__push__(buffer_tuple)

    ## DEF

    def __remove__(self, buffer_tuple):
        """
            remove a tuple from the buffer
        """
        tuple_value = self.buffer.pop(buffer_tuple, None)
        if tuple_value is None:
            return False, None
            
        # Add back the memory to the buffer based on what we allocated for the tuple
        self.free_slots += 1

        if tuple_value[PREV_BUFFER_ENTRY] is None and tuple_value[NEXT_BUFFER_ENTRY] is None: # if only one tuple
            self.head = None
            self.tail = None
        elif tuple_value[PREV_BUFFER_ENTRY] is None: # if we remove the top tuple
            self.head = tuple_value[NEXT_BUFFER_ENTRY]
            self.head[PREV_BUFFER_ENTRY] = None # the second becomes the top now
        elif tuple_value[NEXT_BUFFER_ENTRY] is None: # if we remove the bottom tuple
            self.tail = tuple_value[PREV_BUFFER_ENTRY]
            self.tail[NEXT_BUFFER_ENTRY] = None
        else:
            prev = tuple_value[PREV_BUFFER_ENTRY]
            prev[NEXT_BUFFER_ENTRY] = tuple_value[NEXT_BUFFER_ENTRY]
            
            next = tuple_value[NEXT_BUFFER_ENTRY]
            next[PREV_BUFFER_ENTRY] = tuple_value[PREV_BUFFER_ENTRY]

        return True, tuple_value
    ## DEF

    def __push__(self, buffer_tuple):
        """
            Add the given buffer_tuple to the bottom of the buffer
        """
        page_hits = 0
        newEntry = [self.tail, None]
        # pop out the least recent used tuples until we have enough space in buffer for this tuple
        if self.tail is not None:
            while self.free_slots <= 0:
                # self.__remove__(self.head)
                self.free_slots += 1
                self.head = self.head[NEXT_BUFFER_ENTRY]
                self.head[PREV_BUFFER_ENTRY] = None
                self.evicted += 1
                page_hits += 1

            self.tail[NEXT_BUFFER_ENTRY] = newEntry
        else:
            self.head = newEntry

        self.tail = newEntry
        self.buffer[buffer_tuple] = newEntry
        self.free_slots -= 1
        page_hits += 1

        return page_hits

    ## DEF

    ## -----------------------------------------------------------------------
    ## UTILITY METHODS
    ## -----------------------------------------------------------------------

    def __getIndexSize__(self, col_info, indexKeys):
        """Estimate the amount of memory required by the indexes of a given design"""
        # TODO: This should be precomputed ahead of time. No need to do this
        #       over and over again.
        index_size = 0
        for f_name in indexKeys:
            f = col_info.getField(f_name)
            assert f, "Invalid index key '%s.%s'" % (col_info['name'], f_name)
            index_size += f['avg_size']
        index_size += self.address_size
        if self.debug: LOG.debug("%s Index %s Memory: %d bytes",\
            col_info['name'], repr(indexKeys), index_size)
        return index_size
        ## DEF

    def __str__(self):
        buffer_ratio = (self.window_size - self.free_slots) / float(self.window_size)
        return "Buffer Usage %.2f%% [evicted=%d / refreshed=%d / entries=%d / used=%d / total=%d]" % (\
            buffer_ratio*100,
            self.evicted,
            self.refreshed,
            len(self.buffer.keys()),
            self.window_size - self.free_slots,
            self.window_size,
            )
        ## DEF

    def validate(self):
        """Check that the buffer is in a valid state"""
        assert self.free_slots >= 0,\
        "The buffer has a negative remaining space"
        assert self.free_slots <= self.window_size,\
        "The buffer has more remaining space than the original buffer size"
        ## DEF
## CLASS
