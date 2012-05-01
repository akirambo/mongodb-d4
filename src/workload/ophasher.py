# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------
# Copyright (C) 2012
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

import logging
from pprint import pformat

LOG = logging.getLogger(__name__)

class OpHasher:
    
    def __init__(self):
        pass
    ## DEF
    
    def hash(self, op):
        """Compute a deterministic signature for the given operation based on its keys"""
        
        fields = None
        updateFields = None
        
        # QUERY
        if op["type"] == "$query":
            # The query field has our where clause
            print op
            fields = op["content"][0]["query"]
        # UPDATE
        elif op["type"] == "$update":
            # The first element in the content field is the WHERE clause
            fields = op["content"][0]
            updateFields = op['content'][1]
        # INSERT
        elif op["type"] == "$insert":
            fields = op["content"]
        # DELETE
        elif op["type"] == "$delete":
            # The first element in the content field is the WHERE clause
            fields = op["content"][0]
        # UNKNOWN!
        else:
            raise Exception("Unexpected query type: %s" % op["type"])
        
        # Extract the list of fields that are used
        sortedFields = tuple(sorted(fields.keys()))
        
        t = (op["collection"], op["type"], sortedFields)
        h = hash(t)
        
        print fields, t, h
        return h
    ## DEF
    
    def computeFieldsHash(self, fields):
        _sorted = [ ]
        for k, v in fields.iteritems():
            if type(v) == dict:
                pass
            else:
                pass
        ## FOR
        
    
## CLASS