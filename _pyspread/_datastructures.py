#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2008 Martin Manns
# Distributed under the terms of the GNU General Public License
# generated by wxGlade 0.6 on Mon Mar 17 23:22:49 2008

# --------------------------------------------------------------------
# pyspread is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyspread is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyspread.  If not, see <http://www.gnu.org/licenses/>.
# --------------------------------------------------------------------

"""
_datastructures
===============

Provides
  1. Grid object class Grid
  2. Macro user dictionary class Macros
  3. Undo/Redo framework class UnRedo

"""

import types
import UserDict

from itertools import imap, islice, tee, izip

import numpy

from irange import irange, slice_range
from _pyspread._arrayhelper import getflatpos, getshapedpos
from _pyspread._interfaces import string_match,  Digest, UserString
from _pyspread.config import default_cell_attributes

S = None

OPERATORS = ["+", "-", "*", "**", "/", "//",
             "%", "<<", ">>", "&", "|", "^", "~",
             "<", ">", "<=", ">=", "==", "!=", "<>",
            ]

class PyspreadGrid(object):
    """Central data object that provides two numpy based 3D object arrays.

    An array (sgrid) stores strings that contain python expressions.

    Parameters
    ----------
    dimensions : 3 tuple of int
    \tThe dimensions of sgrid (defaults to (10, 10, 10))

    """
        
    def __init__(self, dimensions=(10, 10, 10)):
        """ Init
        
        Parameters
        ----------
        
        dimensions: 3-tuple of Int
        \tRepresents rows, cols and tabs if the grid
        \tMust all be positive
        
        """
        
        global S
        S = self
        
        try:
            self.sgrid = DictGrid(shape=dimensions)
        except (MemoryError, ValueError), error:
            self.sgrid = DictGrid(shape=(1, 1, 1))
            self.sgrid[0, 0, 0] = "Matrix creation failed: " + error
        
        self.macros = Macros({}) # Macros from Macrolist
        
        self.unredo = UnRedo()
        
        self.safe_mode = False # Values are results for all cells if True
        
        self.frozen_cells = {} # Values are results for frozen cells
        
        self._resultcache = {}
        
        self._tabukey = None # Cycle detection key
        
        self._unicode_digest = Digest(acceptable_types=[types.UnicodeType])
    
    def _getshape(self):
        """Returns the shape of the array sgrid"""
        
        return self.sgrid.shape
    
    shape = property(_getshape)
    
    def _eval_cell(self, key):
        """Evaluates one cell"""
        
        # Set up environment for evaluation
        env = globals().copy()
        env.update( {'X':key[0], 'Y':key[1], 'Z':key[2], 'S':self } )
        
        # Check if there is a global assignment
        split_exp = self.sgrid[key].split("=")
        
        # If only 1 term in front of the "=" --> global
        if len(split_exp) > 1 and \
           len(split_exp[0].split()) == 1 and \
           split_exp[1] != "" and \
           (not max(op in split_exp[0] for op in OPERATORS)) and \
           split_exp[0].count("(") == split_exp[0].count(")"):
            glob_var = split_exp[0].strip()
            expression = "=".join(split_exp[1:])
        else:
            glob_var = None
            expression = self.sgrid[key]
        
        try:
            result = eval(expression, env, {})
        except Exception, err:
            result = err
        
        if glob_var is not None:
            globals().update({glob_var: result})
        
        return result
    
    def _get_single_item(self, key):
        """Returns results for one single item. 
        
        key: Iterable of three ints
        \tPosition in grid
        
        """
        
        # If safe mode is activated return code
        if self.safe_mode:
            return self.sgrid[key]
        
        # Frozen cell cache access
        if key in self.frozen_cells:
            return self.frozen_cells[key]
        
        if self._resultcache.has_key(key):
            result = self._resultcache[key]
        elif self.sgrid[key] in [0, None, ""]:
            result = None
        else:
            self._resultcache[key] = \
                KeyError("Circular dependency at %s" % str(key))
            result = self._eval_cell(key)
            self._resultcache[key] = result

        # If value is an exception
        if isinstance(result, Exception):
            # we raise it, unwinding the expression evaluation in the caller
            raise result
        else: 
            # else we return it, allowing eval to use the value 
            return result
    
    def _get_list_keys(self, key, list_dim):
        """Returns a generator of all keys along dimension list_dim
        
        Reduces key dimension by 1 and returns a list of key in that dimension
        
        Parameters
        ----------
        key: Iterable of length 3 of integers or slices with >=1 slice
        
        list_dim: Integer
        \tThe key in this dimension must be a slice
        
        """
        
        assert len(key) == 3
        assert type(key[list_dim]) is types.SliceType
        
        # Iterated dim list
        key_slice = key[list_dim]
        
        try:
            key_slice_start = int(key_slice.start)
        except TypeError:
            key_slice_start = None
            
        try:
            key_slice_stop = int(key_slice.stop)
        except TypeError:
            key_slice_stop = None
            
        try:
            key_slice_step = int(key_slice.step)
        except TypeError:
            key_slice_step = None
        
        list_range = slice_range(key_slice, self.shape[list_dim])
        
        def replace_dim(list_key, base_key=key, dim=list_dim):
            """Replaces element dim in base_key by list_key"""
            
            base_key = list(base_key)
            base_key[dim] = list_key
            return tuple(base_key)
        
        return imap(replace_dim, list_range)
        
    
    def _get_ndim_itemlist(self, key):
        """Returns results for a 3-dim list of items. 
        
        key: Iterable of three slices
        \tPosition in grid
        
        """
        
        def _get_ndim_method(ndim):
            """Returns the method that is called for inner values"""
            
            if ndim == 1: 
                return self._get_single_item
            elif ndim > 1:
                return self._get_ndim_itemlist
            else:
                raise KeyError, "At least one key item must be a slice"
        
        keytypes = map(type, key)
        
        ndim = keytypes.count(types.SliceType)
        ndim_method = _get_ndim_method(ndim)
        
        # Dim of list in grid
        list_dim = keytypes[::-1].index(types.SliceType)
        list_dim = len(keytypes) - list_dim - 1
        
        listkeys, __listkeys = tee(self._get_list_keys(key, list_dim))
        
        __listkeys = list(__listkeys)
        
        if self._tabukey in __listkeys:
            raise KeyError, 'Infinite recursion detected.'
        
        list_range = []
        for listkey in listkeys:
            list_range.append(ndim_method(listkey))
        try:
            list_range = numpy.array(list_range)
        except ValueError:
            return list_range
        
        try: 
            list_range = list_range.transpose(1, 2, 0)
        except ValueError:
            try:
                list_range = list_range.transpose(1, 0)
            except ValueError:
                list_range = list_range.transpose()
        
        return list_range
    
    
    def __getitem__(self, key):
        """Gets items, key may consist of ints or slices"""
        
        if self._tabukey is None:
            self._tabukey = [key]
        
        slicetype = types.SliceType
        if all(type(keyele) != slicetype for keyele in key):
            # Only one cell is called
            try:
                result = self._get_single_item(key)
            except Exception, err:
                result = err
            
        else:
            # Multiple cells in one dimension are called
            try:
                result = self._get_ndim_itemlist(key)
            except Exception, err:
                result = err
        
        if key == self._tabukey:
            self._tabukey = None
        
        return result
    
    def __setitem__(self, pos, value):
        self._resultcache = {}
        
        _old_content = self.sgrid[pos]
        try:
            if _old_content == 0:
                _old_content = u""
        except ValueError:
            _old_content = u""
        
        if _old_content != value:
            undo_operation = (self.__setitem__, [pos, _old_content])
            redo_operation = (self.__setitem__, [pos, value])
        
            self.unredo.append(undo_operation, redo_operation)
        
            self.unredo.mark()
        
        # Test self.sgrid[pos] for already having attributes
        
        attr_names = default_cell_attributes.keys()
        
        attr_data = [self.get_sgrid_attr(pos, name) for name in attr_names]
        default_data = [default_cell_attributes[name]() for name in attr_names]
        
        if attr_data == default_data:
            self.sgrid[pos] = unicode(value)
            return
        
        newitem = UserString(value)
            
        olditem = self.sgrid[pos]
        if type(olditem) is types.UnicodeType:
            olditem = UserString(olditem)
        
        self._copy_attributes(olditem, newitem)

        # Now replace item in grid

        self.sgrid[pos] = newitem

        
    def _copy_attributes(self, olditem, newitem):
        """Copies the cell attributes from olditem to newitem
        
        The value is not affected.
        
        Parameters
        ----------
        olditem: UserString
        \tAttribute source
        newitem: UserString
        \t Attribute target
        
        """
        
        for attr_name in default_cell_attributes.keys():
            try:
                setattr(newitem, attr_name, getattr(olditem, attr_name))
            except AttributeError:
                pass
                
    
    def __len__(self):
        return len(self.sgrid)
    
    
    def isinsclice(self, slc, dim, index):
        """
        Determines if an index is in a slice of dimension dim
        
        Parameters
        ----------
        slc: slice
        \tThe slice for which the test is done
        
        dim: int
        \tThe dimension of the grid
        
        index: int
        \tThe index to be tested
        
        """
        
        length = self.sgrid.shape[dim]
        
        if slc.step is None:
            slc = slice(slc.start, slc.stop, 1)
        
        if slc.step == 0:
            raise ValueError, "slice step cannot be zero"
        
        if slc.step > 0:
            if slc.start is None:
                slc = slice(0, slc.stop, slc.step)
            if slc.stop is None:
                slc = slice(slc.start, length, slc.step)
        elif slc.step < 0:
            if slc.start is None:
                slc = slice(length -1, slc.stop, slc.step)
            if slc.stop is None:
                slc = slice(slc.start, 0, slc.step)
        
        if index < slc.start or index >= slc.stop:
            return False
        
        return (index - slc.start) % slc.step == 0
    
    
    def key_in_slicetuple(self, pos, slc_tuple):
        """Tests if a position is in a 3-tuple of slices or ints"""
        
        inranges = [] # List of bool to store results for each dimension
        
        for i, slc in enumerate(slc_tuple):
            if type(slc) is types.SliceType:
                inranges.append(self.isinsclice(slc, i, pos[i]))
            else:
                inranges.append(slc == pos[i])
        
        return min(inranges)
    
    
    def insert(self, insertionpoint, notoinsert, newcells=None, nocells=False):
        """Insert rows, columns or tables
        
        Parameters:
        -----------
        insertionpoint: 3-tuple or list with 3 elements
        \t3 tuple elements are None except for one element.
        \tThis element corresponds to the dimension of the insertion operation.
        \tand describes the position of the insertion operation.
        notoinsert: int
        \tNo. cols/rows/tables that are to be inserted
        nocells: bool, defaults to False
        \tNo new cells are inserted even though no new cells are provided
        
        """
        
        # The function does only work correctly with correct insertionpoint
        assert len(insertionpoint) == 3
        assert list(insertionpoint).count(None) == 2
        
        self._resultcache = {}
        
        undo_operation = (self.remove, [insertionpoint, notoinsert])
        redo_operation = (self.insert, [insertionpoint, notoinsert, newcells])
        self.unredo.append(undo_operation, redo_operation)
        
        ins_points = list(insertionpoint)
        ins_point = max(ins_points)
        
        axis = ins_points.index(ins_point)
        
        key_update = {}
        del_keys = []
        sgrid = self.sgrid
        
        for key in sgrid:
            if key[axis] >= ins_point:
                new_key = list(key)
                new_key[axis] += notoinsert
                new_key = tuple(new_key)
                key_update[new_key] = sgrid[key]
                del_keys.append(key)
        
        for key in del_keys:
            sgrid.pop(key)
             
        sgrid.update(key_update)
        
        # Restore deleted cells from unredo operation
        sgrid.update(newcells)
        
    def remove(self, removalpoint, notoremove):
        """Remove rows, columns or tables
                
        Parameters:
        -----------
        removalpoint: 3-tuple or list with 3 elements
        \removalpoint must be a 3 tuple, which is None except for one element.
        \tThis element corresponds to the dimension of the removal operation
        \tand describes the position of the removal operation.
        notoremove: int
        \tNo. cols/rows/tables that are to be removed
        
        """
        
        self._resultcache = {}
        
        rmps = list(removalpoint)
        rmp = max(rmps)
        axis = rmps.index(rmp)
        
        key_update = {}
        del_keys = []
        del_key_storage = {}
        sgrid = self.sgrid
        
        for key in sgrid:
            if rmp <= key[axis] < rmp + notoremove:
                # Delete cell
                del_keys.append(key)
                del_key_storage[key] = sgrid[key]
                
            elif rmp <= key[axis]:
                # Move cell
                new_key = list(key)
                new_key[axis] -= notoremove
                new_key = tuple(new_key)
                key_update[new_key] = sgrid[key]
                del_keys.append(key)
        
        for key in del_keys:
            sgrid.pop(key)
             
        sgrid.update(key_update)
        
        undo_operation = (self.insert, 
                          [removalpoint, notoremove, del_key_storage])
        redo_operation = (self.remove, [removalpoint, notoremove])
        self.unredo.append(undo_operation, redo_operation)
    
    
    def _spread_0dim(self, value, pos, shape):
        """Spread single values"""
        
        posx, posy, posz = pos
        
        S.sgrid[posx, posy, posz] = self._unicode_digest(value)
        
        return 1
    
    def _spread_1dim(self, value, pos, shape):
        """Spread 1D values"""
        
        posx, posy, posz = pos
        
        rowsleft = self.sgrid[posx:, :, :].shape[0] - shape[0]
        
        if rowsleft < 0:
            value = value[:shape[0] + rowsleft]
        
        strings = self._get_value_strings(value)
        
        S.sgrid[posx: posx + shape[0], posy, posz] = strings
        ## TODO: Change to dict key update
        return len(strings)
    
    def _spread_2dim(self, value, pos, shape):
        """Spread 2D values"""
        
        posx, posy, posz = pos
        
        rowsleft = self.sgrid[posx:, :, :].shape[0] - shape[0]
        colsleft = self.sgrid[:, posy:, :].shape[1] - shape[1]
        
        if rowsleft < 0:
            value = value[:shape[0] + rowsleft, :]
        if colsleft < 0:
            value = value[:, :shape[1] + colsleft]
        
        strings = self._get_value_strings(value)
        
        S.sgrid[posx: posx + shape[0], \
                posy: posy + shape[1], \
               posz] = strings
        ## TODO: Change to dict key update        
        return len(strings)
        
    def _spread_3dim(self, value, pos, shape):
        """Spread 3D values"""
        
        posx, posy, posz = pos
        
        rowsleft = self.sgrid[posx:, :, :].shape[0] - shape[0]
        colsleft = self.sgrid[:, posy:, :].shape[1] - shape[1]
        tablesleft = self.sgrid[:, :, posz:].shape[2] - shape[2]
        
        if rowsleft < 0:
            value = value[:shape[0] + rowsleft, :, :]
        if colsleft < 0:
            value = value[:, :shape[1] + colsleft, :]
        if tablesleft < 0:
            value = value[:, :, :shape[2] + tablesleft]
        
        strings = self._get_value_strings(value)
        
        S.sgrid[posx: posx + shape[0], \
                posy: posy + shape[1], \
                posz: posz + shape[2]] = strings
        ## TODO: Change to dict key update
        
    def _get_value_strings(self, value):
        """Returns numpy array of string representations of value elements"""
        
        flat_res = numpy.array(map(self._unicode_digest, value.flat))
        return flat_res.reshape(value.shape)
    
    def spread(self, value, pos):
        """Spread values into the grid with the top-left-upmost position pos
        
        Only rectangular matrices can be spread at this time
        Returns number of changed cells.
        
        Parameters
        ----------
        value: Scalar, iterable or array
        \tValues that shall be spread
        pos: 3-tuple of int
        \tValid index of self for top-left value insertion
        
        """
        
        valdim = numpy.ndim(numpy.array(value))
        
        if valdim < 0:
            raise ValueError, "Dimension of " + unicode(value) + " negative"
        
        if valdim > 3:
            raise ValueError, "Dimension of " + unicode(value) + " too high"
        
        value = numpy.array(value)
        
        shape = value.shape
        
        spreadfuncs = [self._spread_0dim, \
                       self._spread_1dim, 
                       self._spread_2dim, 
                       self._spread_3dim]
        
        result = spreadfuncs[valdim](value, pos, shape)
        
        return result

    def findnextmatch(self, startpos, find_string, flags):
        """ Returns a tuple with the position of the next match of find_string
        
        Returns None if string not found.
        
        Parameters:
        -----------
        startpos:   Start position of search
        find_string:String to be searched for
        flags:      List of strings, out ouf 
                    ["UP" xor "DOWN", "WHOLE_WORD", "MATCH_CASE", "REG_EXP"]
        
        """
        
        # Index of current cell in flattened grid
        flatgridpos = getflatpos(self.sgrid, startpos) 
        #print flatgridpos
        # Search in each cell until match
        flatgrid = self.sgrid.flatten('F') # We need Fortran order here
        # Start at flatgridpos
        if "DOWN" in flags:
            searchgrid = numpy.concatenate((flatgrid[flatgridpos:], \
                                        flatgrid[:flatgridpos]))
        elif "UP" in flags:
            flatgridpos += 1
            searchgrid = numpy.concatenate((flatgrid[flatgridpos:], \
                                        flatgrid[:flatgridpos]))
            searchgrid = searchgrid[::-1]
        findpos = None
        for key, datastring in enumerate(searchgrid):
            if datastring != '' and \
               string_match(datastring, find_string, flags) is not None:
                if "DOWN" in flags:
                    correctedpos =  flatgridpos + key
                elif "UP" in flags:
                    correctedpos =  flatgridpos - key - 1
                else:
                    raise AttributeError, "UP xor DOWN flag " + \
                                          "not present in flags"
                findpos = getshapedpos(self.sgrid, correctedpos)
                break
        return findpos
    
    def get_function_cell_indices(self, gridslice = None):
        """
        Get indices for all sgrid cells != 0
        
        Parameters:
        -----------
        gridslice: 3-tuple of slices
        \tThe slice of the grid that is searched. Defaults to whole grid.
        
        """
        if gridslice is None:
            gridslice = tuple([slice(None)]*len(self.sgrid.shape))
        sgrid = self.sgrid[gridslice]
        nonzero = list(set(zip(*numpy.nonzero(sgrid))))
        gridslice = list(gridslice)
        for i in xrange(len(self.sgrid.shape)):
            if gridslice[i].start is None:
                gridslice[i] = slice(0, gridslice[i].stop, gridslice[i].step)
        nonzero = [tuple(cell[i] + gridslice[i].start \
                        for i in xrange(len(self.sgrid.shape))) \
                            for cell in nonzero]
        return nonzero
    
    def set_global_macros(self, macros=None):
        """ Sets macros to global scope """
        
        self._resultcache = {}
        if macros is None: 
            macros = self.macros
        for macroname, macro in macros.iteritems():
            globals()[macroname] = macro
    
    def create_sgrid_attribute(self, key, attribute):
        """Creates an attribute of the sgrid string if not already there
        
        attribute: String
        \tAttribute name
        
        """
        
        sgrid = self.sgrid
        
        try:
            getattr(sgrid[key], attribute)
            has_textattributes = True

        except AttributeError:
            has_textattributes = False

        if not has_textattributes:
            try:
                setattr(sgrid[key], attribute, 
                        default_cell_attributes[attribute]())

            except AttributeError:
                if sgrid[key] != 0:
                    sgrid[key] = UserString(sgrid[key])
                else:
                    sgrid[key] = UserString(u"")
                setattr(sgrid[key], attribute, 
                        default_cell_attributes[attribute]())

    def get_sgrid_attr(self, key, attr):
        """Get attribute attr of obj, returns defaultattr on fail"""
        
        obj = self.sgrid[key]
        
        try:
            return getattr(obj, attr)

        except AttributeError:
            return default_cell_attributes[attr]()

# end of class PyspreadGrid


class Macros(UserDict.IterableUserDict):
    """User dict class for macros.

    This class provides a getter and setter method for storing the full
    macro Python code in the 'macrocode' attribute of the funcdict.

    """
    def get_macro(self, code):
        """ Returns the function derived from the code string code. """
        funcname = code.split("(")[0][3:].strip()
        # Windows exec does not like Windows newline
        code = code.replace('\r\n', '\n')
        exec(code)
        func = eval(funcname, globals(), locals())
        func.func_dict['macrocode'] = code
        return func
        
    def add(self, code):
        """ Adds a macro with the code string 'code' to the macro dict"""
        func = self.get_macro(code)
        if func.__name__ in self:
            return 0
        self[func.__name__] = func
        return func
        
# end of class Macros

class UnRedo(object):
    """Undo/Redo framework class.
    
    For each undoable operation, the undo/redo framework stores the
    undo operation and the redo operation. For each step, a 4-tuple of:
    1) the function object that has to be called for the undo operation
    2) the undo function paarmeters as a list
    3) the function object that has to be called for the redo operation
    4) the redo function paarmeters as a list
    is stored.
    
    One undo step in the application can comprise of multiple operations.
    Undo steps are separated by the string "MARK".
    
    The attributes should only be written to by the class methods.

    Attributes
    ----------
    undolist: List
    \t
    redolist: List
    \t
    active: Boolean
    \tTrue while an undo or a redo step is executed.

    """
    
    def __init__(self):
        """[(undofunc, [undoparams, ...], redofunc, [redoparams, ...]), 
        ..., "MARK", ...]
        "MARK" separartes undo/redo steps
        
        """
        
        self.undolist = []
        self.redolist = []
        self.active = False
        
    def mark(self):
        """Inserts a mark in undolist and empties redolist"""
        
        if self.undolist != [] and self.undolist[-1] != "MARK":
            self.undolist.append("MARK")
    
    def undo(self):
        """Undos operations until next mark and stores them in the redolist"""
        
        self.active = True
        
        while self.undolist != [] and self.undolist[-1] == "MARK":
            self.undolist.pop()
            
        if self.redolist != [] and self.redolist[-1] != "MARK":
            self.redolist.append("MARK")
        
        while self.undolist != []:
            step = self.undolist.pop()
            if step == "MARK": 
                break
            self.redolist.append(step)
            step[0](*step[1])
        
        self.active = False
        
    def redo(self):
        """Redos operations until next mark and stores them in the undolist"""
        
        self.active = True
        
        while self.redolist and self.redolist[-1] == "MARK":
            self.redolist.pop()
        
        if self.undolist:
            self.undolist.append("MARK")
        
        while self.redolist:
            step = self.redolist.pop()
            if step == "MARK": 
                break
            self.undolist.append(step)
            step[2](*step[3])
            
        self.active = False

    def reset(self):
        """Empties both undolist and redolist"""
        
        self.__init__()

    def append(self, undo_operation, operation):
        """Stores an operation and its undo operation in the undolist
        
        undo_operation: (undo_function, [undo_function_atttribute_1, ...])
        operation: (redo_function, [redo_function_atttribute_1, ...])
        
        """
        
        # Check attribute types
        for unredo_operation in [undo_operation, operation]:
            iter(unredo_operation)
            assert len(unredo_operation) == 2
            assert hasattr(unredo_operation[0], "__call__")
            iter(unredo_operation[1])
        
        if not self.active:
            self.undolist.append(undo_operation + operation)

# end of class UnRedo

class DictGrid(UserDict.IterableUserDict):
    def __init__(self, shape=(1000, 100, 10), default_value=None):
        self.set_shape(shape)
        self.default_value = default_value
        
        UserDict.UserDict.__init__(self)
        
    def __getitem__(self, key):
        
        get = UserDict.UserDict.__getitem__
        
        try:
            return get(self, key)
            
        except KeyError:
            return self.default_value
            
        except TypeError:
            # We have a slice
            pass
        
        
        fetchlist = []
        
        for dim_key, index in izip(key, self.indices):
            if type(dim_key) is types.SliceType:
                fetchlist.append([i for i in index[dim_key]])
            else:
                fetchlist.append([dim_key])
        
        #print fetchlist
        keys = [(x, y, z) for x in fetchlist[0] \
                          for y in fetchlist[1] \
                          for z in fetchlist[2]]
        
        result = []
        
        for k in keys:
            try:
                result.append(get(self, k))
            except KeyError:
                result.append(self.default_value)
        
        res_shape = tuple(m for m in map(len, fetchlist) if m > 1)
        
        try:
            return numpy.array(result, dtype="O").reshape(res_shape)
        except:
            return numpy.array([], dtype="O")
    
    def set_shape(self, shape):
        self.shape = shape
        self.indices = [irange(size) for size in self.shape]

# end of class DictGrid
