import os,pickle,gams,pandas as pd,numpy as np,DB2Gams,DataBase, ShockFunction, DataBase_wheels,global_settings

def empty_index(symbol):
    if isinstance(symbol,pd.MultiIndex):
        return pd.MultiIndex.from_tuples([],names=symbol.names)
    elif isinstance(symbol,pd.Index):
        return pd.Index([], name=symbol.name)

def dfelse(x,y,kwargs):
	return y if x not in kwargs else kwargs[x]

def df(x,kwargs):
	"""Modify x using keyword arguments (dicts,kwarg)."""
	return x if x not in kwargs else kwargs[x]

class gms_aux:
	@staticmethod
	def getkeys(g):
		return [x for y in g if isinstance(y,dict) for x in y.keys()]
	@staticmethod
	def getvals(g,var):
		return [x for y in g if isinstance(y,dict) for z,x in y.items() if z == var]
	@staticmethod
	def dropNone(x):
		return x if len(x)==1 else [y for y in x if y!=None]
	@staticmethod
	def flat_or_list(k,v):
		return {k:gms_aux.dropNone(v)} if len(gms_aux.dropNone(v))>1 else v[0]
	@staticmethod
	def merge_ctrees(g):
		return {var: gms_aux.flat_or_list('or',gms_aux.getvals(g,var)) for var in gms_aux.getkeys(g)}
	@staticmethod
	def adjCond(g1,g2,var):
		if var not in g2:
			return g1[var]
		elif not g1[var]:
			return {'not': [g2[var]]}
		else:
			return {'and': [g1[var], {'not': [g2[var]]}]}
	@staticmethod
	def merge_ctrees_negation(g1,g2):
		return {var: gms_aux.adjCond(g1,g2,var) for var in set(g1.keys())-set([x for x,y in g2.items() if not y])}
	@staticmethod
	def create_neg(g,g_add,model):
		return {k:v for k,v in gms_aux.ReadCondition([x[1]for x in g if isinstance(x,list)],model).items() if k in g_add.keys()}
	@staticmethod
	def point(x,model):
		if isinstance(x, str):
			return gms_aux.ReadCondition(model.group_conditions(x),model)
		elif isinstance(x,dict):
			return x
	@staticmethod
	def gcond(g,model):
		return gms_aux.merge_ctrees([gms_aux.point(x,model) for x in g if gms_aux.point(x,model)])
	@staticmethod
	def ReadCondition(g,model):
		if g:
			g_add = gms_aux.gcond(g,model)
			return gms_aux.merge_ctrees_negation(g_add,gms_aux.create_neg(g,g_add,model))
		else:
			return {}

class gmspython:
	""" standard shell for gamspython models """
	def __init__(self,module='gmspython',pickle_path=None,work_folder=None,databases=None,**kwargs):
		if pickle_path is not None:
			with open(pickle_path,"rb") as file:
				self.__dict__ = pickle.load(file).__dict__
			self.model = DB2Gams.gams_model_py(gsettings = DB2Gams.gams_settings(work_folder = work_folder,pickle_path = self.import_settings['settings'],**kwargs))
			[setattr(self,k,v) for k,v in self.std_settings().items() if k in [p for p in self.export_settings['dropattrs'] if p!='model']];
		else:
			[setattr(self,k,v) for k,v in self.std_settings(module=module,work_folder=work_folder,databases=databases,**kwargs).items()];

	# --- 		1: Picling/unpickling/export settings 		--- #
	def std_settings(self,module=None,work_folder=None,databases=None,**kwargs):
		""" add standard attributes to the model. """
		return {'module': module, 'ns': {}, 'ns_local': {}, 'import_settings': {}, 'model_instances': {}, 'checkpoints': {}, 'model': self.stdmodel(work_folder,databases=databases,**kwargs),
				'export_settings': {'dropattrs': ['model_instances','checkpoints','model'],'pklattrs': ['settings']}}

	def stdmodel(self,work_folder,databases=None,**kwargs):
		model = DB2Gams.gams_model_py(gsettings=DB2Gams.gams_settings(work_folder=work_folder,**kwargs))
		if databases is not None:
			[model.settings.add_database(db) for db in databases];
		return model

	def __getstate__(self):
		self.import_settings['settings'] = self.model.settings.export()
		return {key:value for key,value in self.__dict__.items() if key not in self.export_settings['dropattrs']}

	def export(self,name=None,repo=None):
		name = 'gmspython_'+self.model.settings.name if name is None else name
		repo = self.model.settings.data_folder if repo is None else repo
		with open(repo+'\\'+name, "wb") as file:
			pickle.dump(self,file)
		return repo+'\\'+name

	# --- 		2: Interact w. namespace/database 		--- #
	def n(self,symbol,tree=None):
		""" retrieve name from ns or ns_local""" 
		if tree is None:
			return df(symbol,self.ns)
		else:
			return df(symbol,self.ns_local[tree])

	def g(self,symbol,tree=None):
		""" retrieve symbol as gpy_symbol. """
		return self.model.database[self.n(symbol,tree=tree)]

	def get(self,symbol,tree=None):
		""" retrieve symbol as pandas object. """
		return self.model.database.get(self.n(symbol,tree=tree))

	def var_ss(self,symbol,group,db=None):
		""" Return the variable in 'symbol', sliced according to the definition of the 'group'. """
		return self.var_custom_group(symbol,self.group_conditions(group),db=db)

	def var_exo(self,symbol,db=None):
		""" Return the variable in 'symbol', sliced according to the union of all exogenous groups."""
		try:
			return self.var_custom_group(symbol,[g.split(self.model.settings.name+'_',1)[-1] for g in self.exo_groups.keys()],db=db)
		except (ValueError,KeyError,TypeError):
			return None

	def var_endo(self,symbol,db=None):
		""" Return the variable in 'symbol', sliced according to the union of all endogenous groups."""
		try:
			return self.var_custom_group(symbol,[g.split(self.model.settings.name+'_',1)[-1] for g in self.endo_groups.keys()],db=db)
		except (ValueError,KeyError,TypeError):
			return None

	def slice_exo(self,db,copy=True,copy_kwargs={}):
		""" Return a copy of the database 'db', where all variables are sliced according to the exogenous groupings."""
		db_new = db.copy(**copy_kwargs) if copy is True else db
		for var in db.variables['scalar_variables']:
			if self.var_exo(var) is None:
				db_new.series.__delitem__(var)
		for var in db.variables['variables']:
			if self.var_exo(var) is None:
				db_new.series.__delitem__(var)
			else:
				db_new[var] = db[var].rctree_pd(DataBase.gpy_symbol(self.var_exo(var)))
		return db_new

	def var_custom_group(self,symbol,group,db=None):
		""" Retrieve the variable in 'symbol', sliced according to some customized group (defined as a list w. variables/groups)"""
		db = self.model.database if db is None else db
		sname = list(self.ns.keys())[list(self.ns.values()).index(symbol)]
		return db[symbol].rctree_pd(gms_aux.ReadCondition(group,self)[sname])
			
	def add_global_settings(self,version,kwargs_ns={},kwargs_vals={},**kwargs_oth):
		if isinstance(version,str):
			self.global_settings = global_settings.add_settings(version,kwargs_ns=kwargs_ns,kwargs_vals=kwargs_vals,**kwargs_oth)
		else:
			self.global_settings = version
		self.ns = {**self.ns, **self.global_settings.ns}
		DataBase.GPM_database.merge_dbs(self.model.database, self.global_settings.database,'first')

	def setstate(self,state,init=True,kwargs_groups={},kwargs_blocks={}):
		self.model.settings.setstate = state
		if state not in self.model.settings.conf:
			self.model.settings.conf[state] = self.model.settings.std_configuration(state=state)
			if init is True:
				self.initialize_variables()
				self.add_groups(**kwargs_groups)
				self.add_blocks(**kwargs_blocks)

	@property
	def state(self):
		return self.model.settings.state

	# --- 		3: Basic write/run methods 		--- #
	def write_and_run(self,name='baseline',options_add={},options_run={},add_checkpoint=False,write=True,overwrite=False,kwargs_init={},kwargs_groups={},kwargs_blocks={},kwargs_write={},kwargs_mi={}):
		if write is True:
			self.write(kwargs_init=kwargs_init,kwargs_groups=kwargs_groups,kwargs_blocks=kwargs_blocks)
		[db.merge_internal() for db in self.model.settings.databases.values()];
		self.run(name,options_add=options_add,options_run=options_run,add_checkpoint=add_checkpoint,kwargs_db={'name':name},overwrite=overwrite,kwargs_write=kwargs_write,kwargs_mi=kwargs_mi)
		
	def run(self,name,options_add={},options_run={},add_checkpoint=False,overwrite=False,kwargs_db={},kwargs_write={},kwargs_mi={}):
		self.model_instance(name=name,kwargs_mi=kwargs_mi)
		if add_checkpoint is not False:
			self.checkpoints[add_checkpoint] = self.model_instances[name].ws.add_checkpoint()
			options_run = {**options_run, **{'checkpoint': self.checkpoints[add_checkpoint]}}
		self.model_instances[name].run(overwrite=overwrite,kwargs_write=kwargs_write,options_add = options_add, options_run = options_run,kwargs_db=kwargs_db)

	def model_instance(self,name='temp',kwargs_mi={}):
		"""Create model instance"""
		self.model_instances[name] = DB2Gams.gams_model(gsettings=self.model.settings,**kwargs_mi)

	def write(self,repo=None,export_settings=False,kwargs_init={},kwargs_groups={},kwargs_blocks={}):
		""" write components needed for running the model."""
		self.initialize_variables(**kwargs_init)
		self.add_groups(**kwargs_groups)
		self.add_blocks(**kwargs_blocks)
		self.model.run_default(repo=repo,export_settings=export_settings)

	# --- 		4: Write group and block methods 		--- #
	def add_group(self,group,n=''):
		return [x for group_item in self.group_conditions(group) for x in self.adj_group(group_item,n=n)]

	def adj_group(self,group_item,n=''):
		if isinstance(group_item,str):
			return [self.adj_string(group_item,n=n)]
		elif isinstance(group_item,list):
			return [[group_item[0], self.adj_group(group_item[1],n=n)][0]]
		elif isinstance(group_item,dict):
			return [{'name': self.n(var), 'conditions': group_item[var]} for var in group_item]

	def adj_string(self,x,n=''):
		return n+x if self.group_conditions(x) else x

	def add_groups(self,**kwargs):
		if hasattr(self,'sub_groups'):
			[self.model.add_group_to_groups(group_vals,group,**kwargs) for group,group_vals in {**self.sub_groups,**self.endo_groups,**self.exo_groups}.items()];
		else:
			[self.model.add_group_to_groups(group_vals,group,**kwargs) for group,group_vals in {**self.endo_groups,**self.exo_groups}.items()];
		self.model.settings.get_conf('g_endo').update(self.endo_groups.keys())
		self.model.settings.get_conf('g_exo').update(self.exo_groups.keys())

	def add_blocks(self,**kwargs):
		[self.model.blocks.__setitem__(k,v) for k,v in self.blocktext.items()];
		self.model.settings.set_conf('blocks',self.model.settings.get_conf('blocks').union(self.mblocks))

	def reset_settings(self,state=None):
		[setattr(self.model.settings,attr,self.model.settings.std_settings()[attr]) for attr in ['run_file','collect_file']];
		if state=='all':
			[self.model.settings.conf.__setitem__(state,self.model.settings.std_configuration(state=state)) for state in self.model.settings.conf];
		elif state is not None:
			self.model.settings.conf.__setitem__(state,self.model.settings.std_configuration(state=state))

	def calibrate_sneaky(self,db_star, name_base = 'baseline', name_calib = 'calib', kwargs_init = {}, overwrite = False,**kwargs):
		self.initialize_variables(**kwargs_init)
		self.setstate('DC')
		kwargs_write ={'end': DB2Gams.run_text(g_exo=self.exo_groups.keys(),g_endo=self.endo_groups.keys(),blocks=self.model.settings.get_conf('blocks'),name=self.model.settings.get_conf('name'))}
		self.setstate('B')
		self.write_and_run(overwrite=overwrite,write=True,kwargs_write=kwargs_write,add_checkpoint=name_base)
		shock_db,kwargs_shock = ShockFunction.sneaky_db(self.model_instances[name_base].out_db,db_star,**kwargs)
		return self.model_instances[name_base].solve_sneakily(from_cp=True,cp_init=self.checkpoints[name_base],shock_db =shock_db,kwargs_shock=kwargs_shock,kwargs_db={'name':name_calib},model_name=self.model.settings.conf['DC']['name'])

class gmspython_i(gmspython):
	def __init__(self,module='gmspython_i',pickle_path=None,work_folder=None,databases=None,database_kw={},**kwargs_gs):
		databases = [DataBase.GPM_database(**database_kw)] if databases is None else databases
		super().__init__(module=module,pickle_path=pickle_path,work_folder=work_folder,databases=databases,**kwargs_gs)
		if pickle_path is None:
			[setattr(self,k,v) for k,v in self.std_settings_i().items()];

	def std_settings_i(self,**kwargs):
		return {'modules': {}}

	# ---		1: Standard methods			--- #
	def n(self,symbol,module=None,tree=None):
		""" retrieve name from ns or ns_local"""
		if module is None:
			return df(symbol,self.ns) if tree is None else df(symbol,self.ns_local[tree])
		else:
			return self.modules[module].n(symbol,tree=tree)

	def g(self,symbol,module=None,tree=None):
		""" retrieve symbol as gpy_symbol. """
		return self.model.database[self.n(symbol,module=module,tree=tree)]

	def get(self,symbol,module=None,tree=None):
		""" retrieve symbol as pandas object. """
		return self.model.database.get(self.n(symbol,module=module,tree=tree))

	# ---		1.1: Add new modules 		---#
	def add_module(self,module,adjust_placeholders=True,all_=True):
		self.modules[module.model.settings.name] = module
		self.add_database_from_module(module)
		self.add_variable_ns_from_module(module.model.settings.name)
		if adjust_placeholders is True:
			return self.adjust_placeholders(module,all_=all_)

	def add_database_from_module(self,module):
		[DataBase.GPM_database.add_or_merge(self.model.database,module.model.database[sym],'first') for sym in module.model.database.sets_flat];
		[DataBase.GPM_database.add_or_merge(self.model.database,module.model.database[sym],'first') for sym in module.model.database.parameters_flat];
		[DataBase.GPM_database.add_or_merge(self.model.database,module.var_exo(sym),'first') for sym in module.model.database.variables['variables'] if module.var_exo(sym) is not None];
		[DataBase.GPM_database.add_or_merge(self.model.database,module.var_endo(sym),'second') for sym in module.model.database.variables['variables'] if module.var_endo(sym) is not None];
		[DataBase.GPM_database.add_or_merge(self.model.database,module.model.database[sym],'first') for sym in module.model.database.variables['scalar_variables'] if module.var_exo(sym) is not None];
		[DataBase.GPM_database.add_or_merge(self.model.database,module.model.database[sym],'second') for sym in module.model.database.variables['scalar_variables'] if module.var_endo(sym) is not None];

	def add_variable_ns_from_module(self,m):
		self.ns.update({k:v for k,v in self.modules[m].ns.items() if self.try_gtype(k,module=m) in ('variable','scalar_variable')})

	def try_gtype(self,k,module=None):
		try:
			return self.g(k,module=module).gtype
		except KeyError:
			return None

	def adjust_placeholders(self,module,all_=True):
		if all_ is True:
			[self.model.settings.placeholders.__setitem__(k,self.model.database.database.name) for k in module.model.settings.placeholders];

	def merge_settings(self,ls = None,run_file=None,solve=None):
		if ls is None:
			ls = [m.model.settings for m in self.modules.values()]
		self.model.settings.conf = DB2Gams.mgs.merge_conf(ls,self.model.settings.name,solve)
		self.model.settings.files = DB2Gams.mgs.merge_files(ls)
		self.model.settings.run_file = DB2Gams.mgs.merge_run_files(ls,run_file)
		self.model.settings.collect_files = DB2Gams.mgs.merge_collect_files(ls)

	# ---		1.2: Subset variables into endogenous/exogenous 		---#
	def var_endo(self,symbol, db = None):
		db = self.model.database if db is None else db
		try:
			return db[symbol].rctree_pd({'or': [DataBase.gpy_symbol(m.var_endo(symbol)) for m in self.modules.values() if m.var_endo(symbol) is not None]})
		except (ValueError,KeyError,TypeError):
			return None

	def var_exo(self,symbol, db = None):
		db = self.model.database if db is None else db
		try:
			return db[symbol].rctree_pd({'not': [{'or': [DataBase.gpy_symbol(m.var_endo(symbol)) for m in self.modules.values() if m.var_endo(symbol) is not None]}]})
		except (ValueError,KeyError,TypeError):
			return None

	@property
	def exo_groups(self):
		return {k:v for m in self.modules.values() for k,v in m.exo_groups.items()}

	@property
	def endo_groups(self):
		return {k:v for m in self.modules.values() for k,v in m.endo_groups.items()}
	
	def initialize_variables(self,**kwargs):
		pass

	def setstate(self,state):
		self.model.settings.setstate = state
		if state not in self.model.settings.conf:
			self.model.settings.conf[state] = self.model.settings.std_configuration(state=state)
		[m.setstate(state) for m in self.modules.values()];

	def test_endogenous_overlap(self,m1,m2):
		""" Returns a dictionary with variables as keys, and sets with domains of overlap as values. If there is no conflict, these sets are empty.
		 	The domains stored in these sets are endogenous in both modules, and may be a sign of over-identification (non-square model)."""
		def test_intersection(i1,i2):
			if i1 is not None and i2 is not None:
				return set(i1.index).intersection(set(i2.index))
			else:
				return set()
		return {v: test_intersection(m1.var_endo(v),m2.var_endo(v)) for v in m1.model.database.variables_flat}

