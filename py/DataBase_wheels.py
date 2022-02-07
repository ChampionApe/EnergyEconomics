import DataBase, pandas as pd

def append_index_with_1dindex(index1,index2):
	"""
	index1 is a pandas index/multiindex. index 2 is a pandas index (not multiindex).
	Returns a pandas multiindex with the cartesian product of elements in (index1,index2). 
	NB: If index1 is a sparse multiindex, the cartesian product of (index1,index2) will keep this structure.
	"""
	return pd.MultiIndex.from_tuples([a+(b,) for a in index1 for b in index2],names=index1.names+index2.names) if isinstance(index1,pd.MultiIndex) else pd.MultiIndex.from_tuples([(a,b) for a in index1 for b in index2],names=index1.names+index2.names)

def append_index_with_index(index1,index2):
	"""
	index1 is a pandas index/multiindex. index 2 is a pandas index/multiindex.
	Returns a pandas multiindex with the cartesian product of elements in (index1,index2). 
	NB: If index1 is a sparse multiindex, the cartesian product of (index1,index2) will keep this structure.
	"""
	if isinstance(index2,pd.MultiIndex):
		return pd.MultiIndex.from_tuples([a+b for a in index1 for b in index2],names=index1.names+index2.names) if isinstance(index1,pd.MultiIndex) else pd.MultiIndex.from_tuples([(a,) + b for a in index1 for b in index2],names=index1.names+index2.names)
	else:
		return append_index_with_1dindex(index1,index2)

def prepend_index_with_1dindex(index1,index2):
	return pd.MultiIndex.from_tuples([(b,)+a for a in index1 for b in index2],names=index2.names+index1.names) if isinstance(index1,pd.MultiIndex) else pd.MultiIndex.from_tuples([(b,a) for a in index1 for b in index2],names=index2.names+index1.names)

def slice_in_and_out(all_,exceptions=[],add_to_specific=None):
	all_ = all_ if type(all_) is set else set(all_)	
	all_ = all_ if add_to_specific is None else all_.intersection(set(add_to_specific))
	return all_-set(exceptions)

def repeat_variable_windex(var,index):
	if index.name not in var.index.names:
		return pd.concat({i: var for i in index},names=index.names)
	else:
		return var

def map_from_mi(mi,lfrom,lto):
	""" create mapping from one level of the multiindex to the other."""
	return {k:v for k,v in zip(*([mi.get_level_values(lfrom),mi.get_level_values(lto)]))}

def apply_map(index_,map_):
	return [map_[x] for x in index_]

def appmap(map_,mapping,level=None):
	if isinstance(mapping,pd.MultiIndex):
		mapping = map_from_mi(mapping,mapping.names[0],mapping.names[1])
	if isinstance(map_,pd.MultiIndex):
		return pd.MultiIndex.from_arrays([map_.get_level_values(l) for l in map_.droplevel(level).names]+[map_.get_level_values(level).map(mapping)]).reorder_levels(map_.names)
	elif isinstance(map_,pd.Index):
		return map_.map(mapping)

def update_lname_index(ind,oldname,newname):
	if isinstance(ind, pd.MultiIndex):
		return ind.rename(list(map(lambda x: x if x != oldname else newname, ind.names)))
	elif isinstance(ind,pd.Index):
		return ind.rename(newname)

def appmap_s(s,mapping,level=None):
	return pd.Series(s.values, index = appmap(s.index,mapping,level=level), name = s.name)

def appmap_df(df,mapping,level=None):
	return df.set_index(appmap(df.index,mapping,level=level))

class mi:
	""" small collection of multiindex/index operations """
	@staticmethod
	def map_v3(ind,mi,level=None,add_new_name = True):
		""" Swap level in index by mapping from second multiindex  The name of the index is updated if add_new_name is True"""
		if type(level) is str:
			lfrom,lto = level, [x for x in mi.names if x!=level][0]
		elif type(level) is int:
			lfrom = ind.names[level]
			lto = [x for x in mi.names if x !=lfrom][0]
		elif level is None:
			lfrom = [x for x in ind.names if x in mi.names][0]
			lto = [x for x in mi.names if x !=lfrom][0]
		else:
			raise TypeError('Specify level as an integer, string of None')
		mi_map = map_from_mi(mi,lfrom,lto)
		ind_new = appmap(ind,mi_map,level=lfrom)
		return ind_new if add_new_name is False else update_lname_index(ind_new,lfrom,lto)

	@staticmethod 
	def v3_series(s,mi_map,level=None,**kwargs):
		""" map_v1 applied on a pandas series """
		return pd.Series(s.values,index = mi.map_v3(s.index,mi_map,**kwargs),name=s.name)

	@staticmethod
	def map_v1(mi1,mi2,level=None,verify_integrity=False):
		""" swap level of multiindex by mapping from second multiindex. The name of the index level is updated as well"""
		if type(level) is str:
			mi_map = {k:v for k,v in mi2}
			return mi1.set_levels([x if x not in mi_map else mi_map[x] for x in mi1.levels[mi1.names.index(level)]],level=level,verify_integrity=verify_integrity)
		elif type(level) is int:
			mi_map = {k:v for k,v in mi2}
			return mi1.set_levels([x if x not in mi_map else mi_map[x] for x in mi1.levels[level]],level=level,verify_integrity=verify_integrity)
		elif level is None:
			level = [x for x in mi1.names if x in mi2.names][0]
			mi_map = {k:v for k,v in mi2.swaplevel(i=level,j=0)}
			return mi1.set_levels([x if x not in mi_map else mi_map[x] for x in mi1.levels[mi1.names.index(level)]],level=level,verify_integrity=verify_integrity)

	@staticmethod
	def v1_series(s,mi_map,level=None,**kwargs):
		""" map_v1 applied on a pandas series """
		return pd.Series(s.values,index = mi.map_v1(s.index,mi_map),name=s.name)

	@staticmethod
	def map_v2(mi1,mi2,level=None,name=None):
		""" Replace level of multiindex from mapping mi2. The name of the index level is updated as well."""
		if type(level) is str:
			mi_map = {k:v for k,v in mi2}
			name = [name] if name is not None else [n for n in mi2.names if n!=level]
		elif type(level) is int:
			mi_map = {k:v for k,v in mi2}
			name = [name] if name is not None else [mi2.names[n] for n in range(len(mi2.names)) if n!=level]
		elif level is None:
			level = [x for x in mi1.names if x in mi2.names][0]
			name = [name] if name is not None else [n for n in mi2.names if n!=level]
			mi_map = {k:v for k,v in mi2.swaplevel(i=level,j=0)}
		return pd.MultiIndex.from_tuples(zip(*([mi1.get_level_values(x) for x in mi1.droplevel(level).names]+[mi1.get_level_values(level).map(mi_map)])),names=mi1.droplevel(level).names+name)

	@staticmethod
	def v2_series(s,mi_map,level=None,name=None):
		return pd.Series(s.values,index = mi.map_v2(s.index,mi_map,name=name),name=s.name)

	@staticmethod
	def add_ndmi(mi1,mi2,level=None):
		""" Merge a 2d multiindex (mi2) onto multiindex mi1; merge on level."""
		if level is None:
			level = [x for x in mi1.names if x in mi2.names][0]
		lto = [x for x in mi2.names if x not in mi1.names]
		return pd.MultiIndex.from_tuples(zip(*([mi1.get_level_values(x) for x in mi1.names]+[apply_map(mi1.get_level_values(level),map_from_mi(mi2,level,y)) for y in lto])),names=mi1.names+lto)

	@staticmethod
	def add_mi_series(s,mi_map,level=None):
		return pd.Series(s.values,index = mi.add_ndmi(s.index,mi_map,level=level),name=s.name)

class small_updates:
	"""
	Collection of auxiliary database methods. 
	"""
	@staticmethod
	def set_values(db,set_,ns,inplace=True):
		full_map = {x: x if x not in ns else ns[x] for x in db[set_]}
		for set_i in db.alias_all(set_):
			if set_i in db.symbols:
				db[set_i].vals = db[set_i].vals.map(full_map).unique()
			for set_ij in db.sets['subsets']:
				if set_i in db[set_ij].domains:
					db[set_ij].vals = db[set_ij].vals.map(full_map).unique()
			for map_ij in db.sets['mappings']:
				if set_i in db[map_ij].domains:
					db[map_ij].vals = db[map_ij].vals.set_levels(db[map_ij].vals.levels[db[map_ij].domains.index(set_i)].map(full_map),level=set_i,verify_integrity=False)
			for var in db.variables['variables']+db.parameters['parameters']:
				if set_i in db[var].domains:
					if len(db[var].domains)==1:
						db[var].vals.index = db[var].index.map(full_map)
					else:
						db[var].vals.index = db[var].index.set_levels(db[var].index.levels[db[var].domains.index(set_i)].map(full_map),level=set_i,verify_integrity=False)
		return db

	@staticmethod
	def add_index_to_sets(db,index_,exceptions=[],add_to_specific = None,prepend=True):
		all_ = slice_in_and_out(db.sets['subsets']+db.sets['mappings'],exceptions=exceptions,add_to_specific=add_to_specific)
		for set_ in all_:
			db[set_] = prepend_index_with_1dindex(db[set_].vals,index_) if prepend is True else append_index_with_1dindex(db[set_].vals,index_)
		return db

	@staticmethod
	def add_index_to_variables(db,index_,exceptions=[],add_to_specific = None):
		for var in slice_in_and_out(db.variables['variables']+db.parameters['parameters'],exceptions=exceptions,add_to_specific=add_to_specific):
			db[var].index = prepend_index_with_1dindex(db[var].index,index_)
		for scalar in slice_in_and_out(db.variables['scalar_variables'],exceptions=exceptions,add_to_specific=add_to_specific):
			db[scalar] = pd.Series(db.vals, index = index_,name=scalar)
		for scalar in slice_in_and_out(db.variables['scalar_parameters'],exceptions=exceptions,add_to_specific=add_to_specific):
			db[scalar] = DataBase.gpy_symbol(pd.Series(db[scalar].vals,index = index_,name=scalar),**{'gtype':'parameter'})

	@staticmethod
	def subset_db(db,index_,exceptions=[],add_to_specific=None):
		""" Only keep values from index_ """
		for set_ in db.alias_all(index_.name):
			index_i = pd.Index(index_,name=set_)
			if set_ in db.symbols:
				db[set_].vals = db.get(set_)[db.get(set_).isin(index_i)] # subset the set itself
			for sym in slice_in_and_out(db.sets['subsets']+db.sets['mappings'],exceptions=exceptions,add_to_specific=add_to_specific):
				if set_ in db[sym].domains:
					db[sym].vals = db.get(sym)[db.get(sym).get_level_values(set_).isin(index_i)].unique()
			for sym in slice_in_and_out(db.parameters['parameters']+db.variables['variables'],exceptions=exceptions,add_to_specific=add_to_specific):
				if index_i.name in db[sym].domains:
					db[sym].vals = db.get(sym)[db.get(sym).index.get_level_values(index_i.name).isin(index_i)]
		return db
