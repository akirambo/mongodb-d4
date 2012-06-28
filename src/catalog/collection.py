# -*- coding: utf-8 -*-

from mongokit import Document

from util import *

## ==============================================
## Collection
## ==============================================
class Collection(Document):
    __collection__ = constants.COLLECTION_SCHEMA
    structure = {
        'name':             unicode,   # The name of the collection
        'shard_keys':       dict,      # The original sharding keys assigned for this collection (if available)
        'indexes':          [dict],    # The original index keys assigned for this collection (if available)
        'data_size':        long,      # The estimated total size of this collection
        'doc_count':        int,       # The estimated number of documents in this collection
        'avg_doc_size':     int,       # The average size of the documents in the collection (bytes)
        'max_pages':        int,       # The maximum number of pages required to scan the collection
        'workload_queries': int,       # The number operations that reference this collection
        'workload_percent': float,     # The percentage of the total workload that touch this collection
        'interesting':      [basestring], # TODO(ckeith)

        ## ----------------------------------------------
        ## FIELDS
        ## ----------------------------------------------
        'fields': {
            unicode: {
                'type':             basestring, # catalog.fieldTypeToString(col_type),
                'fields':           dict,       # nested fields
                'query_use_count':  int,        # The number of times this field is referenced in queries
                'cardinality':      int,        # Number of distinct values
                'selectivity':      int,        # Cardinalty / Tuple Count
                'parent_col':       basestring, # TODO(ckeith)
                'parent_key':       basestring, # TODO(ckeith)
                'parent_conf':      float,      # TODO(ckeith)
            }
        }

    }
    required_fields = [
        'name', 'doc_count'
    ]
    default_values = {
        'shard_keys':           { },
        'indexes':              [ ],
        'doc_count':            0,
        'avg_doc_size':         0,
        'max_pages':            0,
        'workload_queries':     0,
        'workload_percent':     0.0,
        'interesting':          [ ],
        'fields':               { },
    }

    @staticmethod
    def fieldFactory(fieldName, fieldType):
        """Return an uninitialized field dict that can then be inserted into this collection"""
        field = {
            'type':             fieldType,
            'fields':           { },
            'query_use_count':  0,
            'cardinality':      0,
            'selectivity':      0,
            'parent_col':       None,
            'parent_key':       None,
            'parent_conf':      None
        }
        return (field)
    ## DEF

    def getEmbeddedKeys(self):
        """Return all the keys that contain embedded documents"""
        ret = [ ]
        for catalog_key in self["fields"].values():
            if catalog_key.type in [list, dict]:
                ret.append(catalog_key)
        ## FOR
        return (ret)
    ## DEF
## CLASS