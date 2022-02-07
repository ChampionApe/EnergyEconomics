import os, openpyxl, pandas as pd, numpy as np, gams, pickle
from collections.abc import Iterable
from six import string_types

def d2t(x):
	return list(x.items())[0]

def IfInt(x):
	""" Tests if x is an integer + return boolean instead of valueerror"""
	try:
		int(x)
		return True
	except ValueError:
		return False

def return_version(x,dict_):
	""" Test if x is in dict_: If it is not, return x. 
	If it is rename x with x_int where int is the lowest natural number not already defined in dict_"""
	if x not in dict_:
		return x
	elif (x+'_0') not in dict_:
		return x+'_0'
	else:
		maxInt = max([int(y.split('_')[-1]) for y in dict_ if (y.rsplit('_',1)[0]==x and IfInt(y.split('_')[-1]))])
		return x+'_'+str(maxInt+1)

def is_iterable(arg):
	""" test if an argument is iterable and not strings. """
	return isinstance(arg, Iterable) and not isinstance(arg, string_types)

def map_lowest_level(func, x):
	"""Map lowest level of zero or more nested lists."""
	if is_iterable(x):
		return [map_lowest_level(func, i) for i in x]
	else:
		return func(x)

def try_to_int(x):
  """Cast input to int if possible, else return input unchanged."""
  try:
    if str(int(x)) == str(x):
      return int(x)
    else:
      return x
  except ValueError:
    return x

def map_to_int_where_possible(iter):
	"""Returns an iterable where each element is converted to an integer if possible for that element."""
	return map_lowest_level(try_to_int, iter)

def kw_df(kwargs,key,df_val):
	return df_val if key not in kwargs else kwargs[key]

def set_or_subset(s_name,name):
	if s_name in ('index_0',name):
		return 'set'
	else:
		return 'subset'

def agg_type(type_i):
	if type_i in ('scalar_variable','variable'):
		return 'variable'
	elif type_i in ('scalar_parameter', 'parameter'):
		return 'parameter'
	elif type_i in ('set','subset','mapping'):
		return 'set'
	else:
		return type_i

def type_gams(symbol):
	if isinstance(symbol,gams.GamsVariable):
		if symbol_is_scalar(symbol):
			return 'scalar_variable'
		else:
			return 'variable'
	elif isinstance(symbol,gams.GamsParameter):
		if symbol_is_scalar(symbol):
			return 'scalar_parameter'
		else:
			return 'parameter'
	elif isinstance(symbol,gams.GamsSet):
		if len(symbol.domains_as_strings)==1:
			if symbol.domains_as_strings in [['*'], [symbol.name]]:
				return 'set'
			else:
				return 'subset'
		elif symbol.name!='SameAs':
			return 'mapping'

def type_pandas(symbol,name=None,gtype='variable'):
	if isinstance(symbol, pd.Series):
		if gtype == 'parameter':
			return 'parameter'
		else:
			try:
				return symbol.attrs['type']
			except KeyError:
				return 'variable'
	elif isinstance(symbol,pd.MultiIndex):
		return 'mapping'
	elif isinstance(symbol,pd.Index):
		return set_or_subset(symbol.name,name)
	elif isinstance(symbol,(int,float,str,np.generic)):
		return 'scalar_parameter' if gtype in ('scalar_parameter','parameter') else 'scalar_variable'

def all_na(x):
	"""Returns bool of whether a series or scalar consists of all NAs"""
	if is_iterable(x):
		return all(pd.isna(x))
	else:
		return pd.isna(x)

def merge_symbol_records(series, symbol):
	"""Convert Pandas series to records in a GAMS Symbol"""
	if isinstance(symbol, gams.GamsSet):
		attr = "text"
	elif isinstance(symbol, gams.GamsVariable):
		attr = "level"
	elif isinstance(symbol, gams.GamsParameter):
		attr = "value"
	for k, v in series.items():
		setattr(symbol.merge_record(k), attr, v)

def set_symbol_records(symbol, value):
	"""Convert Pandas series to records in a GAMS Symbol"""
	if isinstance(symbol, gams.GamsSet):
		if isinstance(value, pd.Index):
			texts = getattr(value, "texts", None)
			value = texts if texts is not None else pd.Series(map(str, value), index=value)
		def add_record(symbol, k, v):
			if not all_na(v):
				symbol.add_record(k).text = str(v)
	elif isinstance(symbol, gams.GamsVariable):
		def add_record(symbol, k, v):
			if not all_na(v):
				symbol.add_record(k).level = v
	elif isinstance(symbol, gams.GamsParameter):
		def add_record(symbol, k, v):
			if not all_na(v):
				symbol.add_record(k).value = v
	else:
		TypeError(f"{type(symbol)} is not supported")
	symbol.clear()
	if symbol_is_scalar(symbol):
		add_record(symbol, None, value)
	elif list(value.keys()) == [0]:
		add_record(symbol, None, value[0])
	else:
		for k, v in value.items():
			add_record(symbol, map_lowest_level(str, k), v)

def py_from_gams_symbol(symbol):
	if isinstance(symbol, gams.GamsSet):
		return index_from_symbol(symbol)
	elif isinstance(symbol, gams.GamsVariable):
		if symbol_is_scalar(symbol):
			return symbol.find_record().level if len(symbol) else None
		else:
			return series_from_variable(symbol)
	elif isinstance(symbol, gams.GamsParameter):
		if symbol_is_scalar(symbol):
			return symbol.find_record().value if len(symbol) else None
		else:
			return series_from_parameter(symbol)
	# elif isinstance(symbol, gams.GamsEquation):
	# 	return symbol.name

def get_domains_from_index(index, name):
	if hasattr(index, "domains"):
		domains = index.domains
	elif hasattr(index, "name"):
		domains = index.names
	else:
		domains = [index.name]
	return ["*" if i in (None, name) else i for i in domains]

def adjust_index(self, name, index, explanatory_text="", texts=None, domains=None):
	"""
	Adjust an index to the format used by GamsPandasDatabase.
	"""
	if len(index) and isinstance(index[0], pd.Index):
		multi_index = pd.MultiIndex.from_product(index)
		multi_index.names = [getattr(i, "name", None) for i in index]
		index = multi_index
	elif isinstance(index, pd.Index):
		index = index.copy()
	else:
		index = pd.Index(index)
	index.explanatory_text = explanatory_text
	if texts is None:
		texts = map_lowest_level(str, index)
	index.texts = pd.Series(texts, index=index)
	index.texts.name = index.name
	if domains is None:
		domains = ["*" if i in (None, name) else i for i in get_domains_from_index(index, name)]
	index.domains = domains
	index.names = domains
	index.name = name
	return index

def index_names_from_symbol(symbol):
	"""Return the domain names of a GAMS symbol,
	except ['*'] cases are replaced by the name of the symbol
	and ['*',..,'*'] cases are replaced with ['index_0',..'index_n']
	"""
	index_names = list(symbol.domains_as_strings)
	if index_names == ["*"]:
		return [symbol.name]
	if index_names.count("*") > 1:
		for i, name in enumerate(index_names):
			if name == "*":
				index_names[i] = f"index_{i}"
	return index_names

def index_from_symbol(symbol):
	"""Return a Pandas Index based on the records and domain names of a GAMS symbol."""
	if len(symbol.domains_as_strings) > 1:
		keys = map_to_int_where_possible([rec.keys for rec in symbol])
		index = pd.MultiIndex.from_tuples(keys, names=index_names_from_symbol(symbol))
		index.name = symbol.name
	elif len(symbol.domains_as_strings) == 1:
		keys = map_to_int_where_possible([rec.keys[0] for rec in symbol])
		index = pd.Index(keys, name=index_names_from_symbol(symbol)[0])
	else:
		return None
	if isinstance(symbol, gams.GamsSet):
		index.text = symbol.text
		index.domains = symbol.domains_as_strings
		index.texts = pd.Series([rec.text for rec in symbol], index, name=symbol.name)
	return index

def symbol_is_scalar(symbol):
	return not symbol.domains_as_strings

def series_from_variable(symbol, attr="level"):
	"""Get a variable symbol from the GAMS database and return an equivalent Pandas series."""
	return pd.Series([getattr(rec, attr) for rec in symbol], index_from_symbol(symbol), name=symbol.name)

def series_from_parameter(symbol):
	"""Get a parameter symbol from the GAMS database and return an equivalent Pandas series."""
	return pd.Series([rec.value for rec in symbol], index_from_symbol(symbol), name=symbol.name)

def sunion_empty(ls):
	""" return empty set if the list of sets (ls) is empty"""
	try:
		return set.union(*ls)
	except TypeError:
		return set()