import pandas as pd, DataBase, nesting_trees, DataBase_wheels

def df(x,kwargs):
	"""
	Modify x using kwargs.
	"""
	return x if x not in kwargs else kwargs[x]

class nesting_tree:
	"""
	Collection of nesting_trees that can be initialized from data or trees.
	"""
	def __init__(self,name="",**kwargs):
		self.name=name
		self.version = 'std'
		self.trees = {}
		self.database = DataBase.GPM_database(**{'name':self.name})

	def add_tree(self,tree,tree_name="",**kwargs):
		"""
		Add a nesting tree to the collection of trees.
		"""
		if type(tree) is str:
			self.trees[tree_name] = nesting_trees.tree_from_data(tree,tree_name=tree_name,**kwargs)
		elif type(tree) is dict:
			self.trees[tree_name] = nesting_trees.nt(tree=tree,tree_name=tree_name,**kwargs)
		elif isinstance(tree,nt):
			self.trees[tree.name] = tree
		else:
			raise TypeError("'tree' must be either a string (file-path for excel data), a dictionary (w. tree-structure), or a nesting_tree (python class).")

	def run_all(self,s0=None,Q2Ps={},**kwargs):
		"""
		For all nesting trees in self.trees, retrieve information on inputs, aggregates, outputs, and mappings.
		"""
		[self.trees[tree].run_all(**kwargs) if tree not in Q2Ps else self.trees[tree].run_all(Q2P=Q2Ps[tree],**kwargs) for tree in self.trees];
		self.aggregate_sector(**kwargs)
		self.prune_trees()
		self.reverse_temp_namespace()
		if s0 is not None:
			self.add_sector(s0,**kwargs)

	def reverse_temp_namespace(self):
		combine_temp_namespaces = [self.trees[tree].temp_namespace for tree in self.trees if self.trees[tree].temp_namespace is not None]
		reverse_namespace = {v: k for dict_ in combine_temp_namespaces for k,v in dict_.items()}
		DataBase_wheels.small_updates.set_values(self.database,self.n,reverse_namespace)
		for tree in self.trees:
			DataBase_wheels.small_updates.set_values(self.trees[tree].database,self.n,reverse_namespace)

	def aggregate_sector(self,**kwargs):
		""" Aggregate sector from combination of trees. """
		self.n,self.nn, self.nnn = list(self.trees.values())[0].n, list(self.trees.values())[0].nn, list(self.trees.values())[0].nnn
		self.inp = df('inp',kwargs) # inputs in sector,
		self.out = df('out',kwargs) # outputs from sector, 
		self.int = df('int',kwargs) # intermediate goods used in nesting,
		self.fg = df('fg',kwargs) # final goods (inputs+outputs),
		self.wT = df('wT',kwargs) # intermediate goods + inputs.
		self.map_all = df('map_all',kwargs) # merged mappings from all sectors
		self.kno_out = df('kno_out',kwargs) # knots in nests of type_io == 'output'.
		self.kno_inp = df('kno_inp',kwargs) # knots in nests of type_io == 'input'.
		self.aggregate_sector_sets(**kwargs) # define main sets/subsets of the aggregate sector.
		self.tree_subsets() # define subsets of the aggregate-sector-sets in each tree
		self.adjust_trees_from_agg() # adjust some of the sets in individual trees with information from aggregate sector sets.
		if 'Q2P' in (tree.version for tree in self.trees.values()):
			self.adjust_for_Q2P(**kwargs)

	def aggregate_sector_sets(self,**kwargs):
		self.database.update_alias(alias=pd.MultiIndex.from_tuples([(self.n,self.nn), (self.n,self.nnn)]))
		self.database[self.n] = pd.Index(set.union(*[set(tree.database.get(tree.n)) for tree in self.trees.values()]), name=self.n)
		self.database[self.map_all] = pd.MultiIndex.from_tuples(set.union(*[set(tree.database.get(tree.map_)) for tree in self.trees.values()]), names = [self.n,self.nn])
		# Define inputs/outputs from all trees:
		inputs_all = set.union(*[set(tree.database.get(tree.inp)) if tree.type_io=='input' else set(tree.database.get(tree.out)) for tree in self.trees.values()])
		outputs_all = set.union(*[set(tree.database.get(tree.inp)) if tree.type_io=='output' else set(tree.database.get(tree.out)) for tree in self.trees.values()])
		# Define database, and add inputs,outputs,intermediates,all,final goods, and withoutTax types, all for the aggregate sector:
		self.database[self.inp] = pd.Index(inputs_all-outputs_all, name = self.n)
		self.database[self.out] = pd.Index(outputs_all-inputs_all, name = self.n)
		self.database[self.int] = pd.Index(set(self.database.get(self.n))-set(self.database.get(self.inp))-set(self.database.get(self.out)), name = self.n)
		self.database[self.fg] = pd.Index(set(self.database.get(self.inp)).union(set(self.database.get(self.out))), name = self.n)
		self.database[self.wT] = pd.Index(set(self.database.get(self.inp)).union(set(self.database.get(self.int))), name = self.n)
		# Aggregates in output-types, and input-types (if they exists):
		if 'output' in (tree.type_io for tree in self.trees.values()):
			self.database[self.kno_out] = pd.Index(set.union(*[set(tree.database.get(tree.kno)) for tree in self.trees.values() if tree.type_io=='output']), name = self.n)
		else:
			self.database[self.kno_out] = pd.Index([], name=self.n)
		if 'input' in (tree.type_io for tree in self.trees.values()):
			self.database[self.kno_inp] = pd.Index(set.union(*[set(tree.database.get(tree.kno)) for tree in self.trees.values() if tree.type_io=='input']), name = self.n)
		else:
			self.database[self.kno_inp] = pd.Index([], name=self.n)

	def tree_subsets(self,**kwargs):
		# Define subsets of the aggregate version in each tree:
		for tree in self.trees.values():
			tree.tree_out = self.out+'_'+tree.name
			if tree.type_io=='input':
				tree.database[tree.tree_out] = pd.Index(set(tree.database.get(tree.out)).intersection(set(self.database.get(self.out))), name = tree.n)
			elif tree.type_io=='output':
				tree.database[tree.tree_out] = pd.Index(set(tree.database.get(tree.inp)).intersection(set(self.database.get(self.out))), name = tree.n)

	def adjust_trees_from_agg(self):
		for tree in self.trees.values():
			tree.knots = 'kno_'+tree.name # knots in tree
			tree.kno_no = 'kno_no_'+tree.name # not output version
			tree.bra_o  = 'bra_o_'+tree.name # branch, output
			tree.bra_no = 'bra_no_'+tree.name # branch, not output
			tree.database[tree.knots] = tree.database.get(tree.kno)
			if tree.type_io=='input':
				tree.database[tree.kno_no] = pd.Index(set(tree.database.get(tree.kno))-set(self.database.get(self.out)),name=tree.n)
				tree.database[tree.bra_o] = pd.Index(tree.database.get(tree.map_).get_level_values(0)[tree.database.get(tree.map_).get_level_values(1).isin(self.database.get(self.out))].unique(), name=tree.n)
			elif tree.type_io=='output':
				tree.database[tree.bra_o] = pd.Index(set(tree.database.get(tree.bra)).intersection(set(self.database.get(self.out))), name=tree.n)
			tree.database[tree.bra_no] = pd.Index(set(tree.database.get(tree.bra))-set(tree.database.get(tree.bra_o)), name=tree.n)

	def adjust_for_Q2P(self,**kwargs):
		self.version = 'Q2P'
		self.PwT_dom = df('PwT_dom',kwargs)
		self.database[self.PwT_dom] = pd.Index(set(self.database.get(self.wT))-set.union(*[set(tree.database.get(tree.OnlyQ)) for tree in self.trees.values() if tree.version=='Q2P']), name = self.n)

	def prune_trees(self):
		"""
		Create set of sets/attributes from nesting trees that are not needed once the information has been applied in model.
		"""
		self.prune_trees = set(['kno','bra','inp','out','OnlyQ'])

	def add_sector(self,s,add_to_existing=True,excep_global=['fg'],local_exceptions={},**kwargs):
		self.s = 's' if 's' not in kwargs else kwargs['s']
		self.s0 = s
		self.add_sector_to_sets(add_to_existing=add_to_existing)
		self.add_sector_to_subsets(exceptions=excep_global)
		self.add_sector_to_variables(exceptions=excep_global)
		for tree in self.trees:
			self.add_sector_to_local(tree,exceptions=local_exceptions[tree] if tree in local_exceptions else [])

	def add_sector_to_sets(self,add_to_existing=True):
		for db in [self.database]+[self.trees[tree].database for tree in self.trees]:
			if self.s not in db.symbols:
				db[self.s] = pd.Index([self.s0],name=self.s)
			elif add_to_existing is True:
				db[self.s].vals = db[self.s].vals.union(pd.Index([self.s0],name=self.s))

	def dvbk(self,obj,exceptions):
		return [obj[k] if k in obj else k for k in exceptions]

	def add_sector_to_subsets(self,exceptions=['fg']):
		exceptions = ['alias_']+self.dvbk(self.__dict__,exceptions)
		[self.add_sector_to_subset(ss,db=self.database) for ss in set(self.database.sets['subsets']+self.database.sets['mappings'])-set(exceptions)];

	def add_sector_to_variables(self,exceptions=[]):
		exceptions = self.dvbk(self.__dict__,exceptions)
		[self.add_sector_to_variable(var,db=self.database) for var in set(self.database.variables_flat+self.database.parameters_flat)-set(exceptions)];

	def add_sector_to_local(self,tree,exceptions=[]):
		exceptions = ['alias_']+self.dvbk(self.trees[tree].__dict__,exceptions)
		[self.add_sector_to_subset(ss,db=self.trees[tree].database) for ss in set(self.trees[tree].database.sets['subsets']+self.trees[tree].database.sets['mappings'])-set(exceptions)];
		[self.add_sector_to_variable(var,db=self.trees[tree].database) for var in set(self.trees[tree].database.variables_flat+self.trees[tree].database.parameters_flat)-set(exceptions)];

	def add_sector_to_subset(self,subset,db):
		if self.s not in db[subset].domains:
			db[subset] = DataBase_wheels.prepend_index_with_1dindex(db[subset].index,db.get(self.s)[db.get(self.s)==self.s0])

	def add_sector_to_variable(self,var,db):
		if db[var].gtype in ('scalar_parameter','scalar_variable'):
			gtype = db[var].gtype
			db[var] = pd.Series(db[var],index=db.get(self.s)[db.get(self.s)==self.s0],name=var)
			db[var].gtype = gtype.split('_')[-1]
		if self.s not in db[var].domains:
			db[var].vals.index = DataBase_wheels.prepend_index_with_1dindex(db[var].index, db.get(self.s)[db.get(self.s)==self.s0])

class nesting_tree_hh:
	"""
	Collection of nesting_trees that can be initialized from data or trees.
	"""
	def __init__(self,name="",**kwargs):
		self.name=name
		self.version = df('v1',kwargs)
		self.trees = {}

	def add_tree(self,tree,tree_name="",**kwargs):
		"""
		Add a nesting tree to the collection of trees.
		"""
		if type(tree) is str:
			self.trees[tree_name] = nesting_trees.tree_from_data(tree,tree_name=tree_name,**kwargs)
		elif type(tree) is dict:
			self.trees[tree_name] = nesting_trees.nt(tree=tree,tree_name=tree_name,**kwargs)
		elif isinstance(tree,nt):
			self.trees[tree.name] = tree
		else:
			raise TypeError("'tree' must be either a string (file-path for excel data), a dictionary (w. tree-structure), or a nesting_tree (python class).")

	def add_ns(self,postfix = '',**kwargs):
		self.n,self.nn, self.nnn = list(self.trees.values())[0].n, list(self.trees.values())[0].nn, list(self.trees.values())[0].nnn
		self.inp = df('inp',kwargs)+postfix # inputs in sector.
		self.out = df('out',kwargs)+postfix # outputs from sector.
		self.int = df('int',kwargs)+postfix # intermediate goods used in nesting.
		self.int_temp = df('int_temp',kwargs)+postfix # intertemporal optimization goods. 
		self.exo = df('exo',kwargs)+postfix # exogenous variables, per default not included in the nesting structure.
		self.kno = df('kno',kwargs)+postfix # knots in nesting structure.
		self.map_all = df('map_all',kwargs)+postfix # mappings.
		if self.version == 'v1':
			self.top = df('top',kwargs)+postfix # subset of most-upper aggregates in the nesting structure.
		self.database = DataBase.GPM_database(alias=pd.MultiIndex.from_tuples([(self.n,self.nn), (self.n, self.nnn)]),**{'name': self.name})

	def add_subsets(self,IO):
		self.database[self.inp] = IO.get('inp_HH')
		self.database[self.out] = IO.get('out_HH')

	def add_tree_subsets(self):
		for tree_name,tree in self.trees.items():
			self.database[tree.inp] = tree.database.get(tree.n)[tree.database.get(tree.n).isin(self.database[self.inp])]
			self.database[tree.out] = tree.database.get(tree.n)[tree.database.get(tree.n).isin(self.database[self.out])]
			for attr in ('kno','map_'):
				self.database[getattr(tree,attr)] = tree.database.get(getattr(tree,attr))
			[setattr(tree,attr,attr+'_'+tree_name) for attr in ('qs_qs','qd_qd','qs_qd','qd_qs','int_temp')];
			self.database[tree.qs_qs] = tree.database.get(tree.map_)[(tree.database.get(tree.map_).get_level_values(self.n).isin(self.database.get(tree.out))) & (tree.database.get(tree.map_).get_level_values(self.nn).isin(self.database.get(tree.out)))].get_level_values(self.n).unique()
			self.database[tree.qs_qd] = tree.database.get(tree.map_)[(tree.database.get(tree.map_).get_level_values(self.n).isin(self.database.get(tree.out))) & ~(tree.database.get(tree.map_).get_level_values(self.nn).isin(self.database.get(tree.out)))].get_level_values(self.n).unique()
			self.database[tree.qd_qd] = tree.database.get(tree.map_)[~(tree.database.get(tree.map_).get_level_values(self.n).isin(self.database.get(tree.out))) & ~(tree.database.get(tree.map_).get_level_values(self.nn).isin(self.database.get(tree.out)))].get_level_values(self.n).unique()
			self.database[tree.qd_qs] = tree.database.get(tree.map_)[~(tree.database.get(tree.map_).get_level_values(self.n).isin(self.database.get(tree.out))) & (tree.database.get(tree.map_).get_level_values(self.nn).isin(self.database.get(tree.out)))].get_level_values(self.n).unique()
			self.database[tree.int_temp] = tree.database.get(tree.n)[tree.database.get(tree.n).isin(self.database.get(self.int_temp))]

	def run_all(self,IO,s0=None,Q2Ps={},int_temp=[],postfix='',**kwargs):
		"""
		For all nesting trees in self.trees, retrieve information on inputs, aggregates, outputs, and mappings.
		"""
		[self.trees[tree].run_all(**kwargs) if tree not in Q2Ps else self.trees[tree].run_all(Q2P=Q2Ps[tree],**kwargs) for tree in self.trees];
		self.add_ns(postfix=postfix,**kwargs)
		self.add_subsets(IO)
		self.add_sector_aggregates(int_temp)
		self.add_tree_subsets()
		self.reverse_temp_namespace()
		if s0 is not None:
			self.add_sector(s0,**kwargs)

	def add_sector_aggregates(self,int_temp):
		self.database[self.n] = pd.Index(set.union(*[set(tree.database.get(tree.n)) for tree in self.trees.values()]), name=self.n)
		self.database[self.int] = self.database.get(self.n)[~self.database.get(self.n).isin(self.database.get(self.inp).union(self.database.get(self.out)))]
		self.database[self.kno] = pd.Index(set.union(*[set(tree.database.get(tree.kno)) for tree in self.trees.values()]), name=self.n)
		self.database[self.map_all] = pd.MultiIndex.from_tuples(set.union(*[set(tree.database.get(tree.map_)) for tree in self.trees.values()]), names = [self.n,self.nn])
		self.database[self.int_temp] = pd.Index(int_temp,name=self.n)
		self.database[self.exo] = pd.Index(set(self.database.get(self.inp).union(self.database.get(self.out)))-set(self.database.get(self.n)),name=self.n)
		self.database[self.n] = self.database.get(self.n).union(self.database.get(self.exo))
		if self.version == 'v1':
			self.database[self.top] = pd.Index(set(self.database.get(self.kno))-set.union(*[set(tree.database.get(tree.bra)) for tree in self.trees.values()]), name=self.n)

	def reverse_temp_namespace(self):
		combine_temp_namespaces = [self.trees[tree].temp_namespace for tree in self.trees if self.trees[tree].temp_namespace is not None]
		reverse_namespace = {v: k for dict_ in combine_temp_namespaces for k,v in dict_.items()}
		DataBase_wheels.small_updates.set_values(self.database,self.n,reverse_namespace)
		for tree in self.trees:
			DataBase_wheels.small_updates.set_values(self.trees[tree].database,self.n,reverse_namespace)

	def add_sector(self,s,add_to_existing=True,excep_global=['fg'],local_exceptions={},**kwargs):
		self.s = 's' if 's' not in kwargs else kwargs['s']
		self.s0 = s
		self.add_sector_to_sets(add_to_existing=add_to_existing)
		self.add_sector_to_subsets(exceptions=excep_global)
		self.add_sector_to_variables(exceptions=excep_global)
		for tree in self.trees:
			self.add_sector_to_local(tree,exceptions=local_exceptions[tree] if tree in local_exceptions else [])

	def add_sector_to_sets(self,add_to_existing=True):
		for db in [self.database]+[self.trees[tree].database for tree in self.trees]:
			if self.s not in db.symbols:
				db[self.s] = pd.Index([self.s0],name=self.s)
			elif add_to_existing is True:
				db[self.s].vals = db[self.s].vals.union(pd.Index([self.s0],name=self.s))

	def dvbk(self,obj,exceptions):
		return [obj[k] if k in obj else k for k in exceptions]

	def add_sector_to_subsets(self,exceptions=['fg']):
		exceptions = ['alias_']+self.dvbk(self.__dict__,exceptions)
		[self.add_sector_to_subset(ss,db=self.database) for ss in set(self.database.sets['subsets']+self.database.sets['mappings'])-set(exceptions)];

	def add_sector_to_variables(self,exceptions=[]):
		exceptions = self.dvbk(self.__dict__,exceptions)
		[self.add_sector_to_variable(var,db=self.database) for var in set(self.database.variables_flat+self.database.parameters_flat)-set(exceptions)];

	def add_sector_to_local(self,tree,exceptions=[]):
		exceptions = ['alias_']+self.dvbk(self.trees[tree].__dict__,exceptions)
		[self.add_sector_to_subset(ss,db=self.trees[tree].database) for ss in set(self.trees[tree].database.sets['subsets']+self.trees[tree].database.sets['mappings'])-set(exceptions)];
		[self.add_sector_to_variable(var,db=self.trees[tree].database) for var in set(self.trees[tree].database.variables_flat+self.trees[tree].database.parameters_flat)-set(exceptions)];

	def add_sector_to_subset(self,subset,db):
		if self.s not in db[subset].domains:
			db[subset] = DataBase_wheels.prepend_index_with_1dindex(db[subset].index,db.get(self.s)[db.get(self.s)==self.s0])

	def add_sector_to_variable(self,var,db):
		if db[var].gtype in ('scalar_parameter','scalar_variable'):
			gtype = db[var].gtype
			db[var] = pd.Series(db[var],index=db.get(self.s)[db.get(self.s)==self.s0],name=var)
			db[var].gtype = gtype.split('_')[-1]
		if self.s not in db[var].domains:
			db[var].vals.index = DataBase_wheels.prepend_index_with_1dindex(db[var].index, db.get(self.s)[db.get(self.s)==self.s0])

def merge_nts(nt,nt_other,exceptions=[]):
	""" Merge list of nts (nt_other) into nt. """
	nt.version = merge_version(nt,nt_other)
	merge_globals(nt,nt_other,exceptions=exceptions)
	merge_ntrees(nt,nt_other)

def merge_ntrees(nt,nt_other):
	[add_or_merge(nt,tree) for nt_i in nt_other for tree in nt_i.trees.values()];

def add_or_merge(nt,tree):
	""" if the tree name is not in nt, add as new.""" 
	if tree.name not in nt.trees:
		nt.trees[tree.name] = tree
	elif not all(getattr(tree,attr_i)==getattr(nt.trees[tree.name],attr_i) for attr_i in ('type_io','version','type_f')):
		raise TypeError(f"The trees {tree.name} are not compatible for merging. Check type_io, version, or type_f attributes.")
	else:
		[setattr(nt.trees[tree.name],attr_j) for attr_j in set(nt.trees[tree.name].__dict__.keys())-set(tree.__dict__.keys())];
		nt.trees[tree.name].tree = merge_trees(nt.trees[tree.name].tree,tree.tree)
		nt.trees[tree.name].database.merge_dbs(nt.trees[tree.name].database,tree.database,'first')

def merge_trees(tree1,tree2):
	return {**tree1,**tree2}

def merge_globals(nt,nt_other,exceptions=[]):
	for nt_i in nt_other:
		nt.database.merge_dbs(nt.database,nt_i.database,'first')
	merge_version(nt,nt_other)
	merge_attrs(nt,nt_other,exceptions=exceptions)
	merge_s0(nt,nt_other)

def merge_version(nt,nt_other):
	return 'std' if all([nt_i.version=='std' for nt_i in [nt]+nt_other]) else 'Q2P'

def merge_attrs(nt,nt_other,exceptions=[]):
	[setattr(nt,attr_j) for nt_i in nt_other for attr_j in set(nt_i.__dict__.keys())-set(nt.__dict__.keys())-set(exceptions)];

def merge_s0(nt,nt_other):
	if hasattr(nt,'s0'):
		sectors = set([nt_i.s0 for nt_i in nt_other+[nt] if hasattr(nt_i,'s0')])
		if len(sectors)>1:
			nt.s0 = sectors
	return sectors