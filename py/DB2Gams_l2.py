from DB2Gams_l1 import *
import shutil, regex_gms

def df(x,y,kwargs):
	return y if x not in kwargs else kwargs[x]

def add_group(group,db):
	out = ''
	for g in group:
		if isinstance(g,dict):
			out += d2g(g,db)
		elif isinstance(g,list):
			out += l2g(g,db=db)
		elif isinstance(g,str):
			out += g+'\n'
	return out

def d2g(d,db):
	return db[d['name']].write(conditions=rc_d2g(d,db))+' "{text}"\n'.format(text=df('text','',d))

def rc_d2g(d,db):
	if 'conditions' not in d:
		return None
	elif isinstance(d['conditions'],str):
		return d['conditions']
	else:
		return db[d['name']].rctree_gams(d['conditions'])

def l2g(g,db=None):
	""" a list with two elements indicate '+/-' in first element (add or subtract to/from group), and variable in second. If second is dict, this is written as a variable."""
	if isinstance(g[1], dict):
		return ''.join([g[0],d2g(g[1],db)])
	else:
		return ''.join(g)+'\n'

def try_(kwargs,key):
	try: 
		kwargs[key]
	except KeyError:
		return {}

def iteNone(x):
	return x if x is not None else [x]

def NoneIfAllNone(x):
	if x is None:
		return x
	else:
		return None if not any(x) else x

class OrdSet:
	def __init__(self,i=[]):
		self.v = list(dict.fromkeys(i))

	def __iter__(self):
		return iter(self.v)

	def __len__(self):
		return len(self.v)

	def __getitem__(self,item):
		return self.v[item]

	def __setitem__(self,item,value):
		self.v[item] = value

	def __add__(self,o):
		return OrdSet(self.v+list(o))

	def __sub__(self,o):
		return OrdSet([x for x in self.v if x not in o])

	def union(self,*args):
		return OrdSet(self.__add__([x for l in args for x in l]))

	def intersection(self,*args):
		return OrdSet([x for l in self.union(args) for x in l if x in self.v])

	def update(self,*args):
		self.v = self.union(*args).v

class gams_settings:
	def __init__(self,pickle_path=None,work_folder=None,**kwargs):
		"""
		Pickle_path points to the pickle file with a gams_settings object.
		work_folder can be either a string (where to initiate a gams.GamsWorkspace), or a workspace.
		Even if the settings is loaded from a pickle, the work_folder and workspace is updated.
		"""
		if pickle_path is not None:
			self.init_from_pickle(pickle_path,work_folder=work_folder)
		else:
			[setattr(self,key,value) for key,value in self.std_settings().items() if key != 'conf'];
			self.init_ws_wfolder(work_folder)
			self.update_attrs(kwargs)
			[setattr(self,key,value) for key,value in self.std_settings().items() if (key == 'conf') and 'conf' not in kwargs];

	def update_attrs(self,kwargs):
		for key,value in kwargs.items():
			setattr(self,key,value)

	def std_settings(self):
		return {'name': "somename",'placeholders': {},'databases':{},'run_file': None, 'conf': {'B': self.std_configuration()},'setstate': 'B',
				'solvestat':True,'files':{},'collect_file':None,'collect_files':None,'root_file':None,'data_folder':os.getcwd(),
				'import_settings': {},'export_settings': {'dropattrs': ['ws','run_file','collect_file']}}

	def std_configuration(self,state='B'):
		return {'name': self.name+'_'+state if hasattr(self,'name') else state, 'g_endo': OrdSet(), 'g_exo': OrdSet(), 'blocks': OrdSet(), 'solve':None}

	def upd_work_folder(self):
		self.work_folder = self.ws.working_directory

	def upd_workspace(self):
		self.ws = gams.GamsWorkspace(working_directory=self.work_folder)

	def add_default_placeholders(self):
		"""
		Adds the names of the databases to the dictionary of placeholders
		"""
		for db in self.databases:
			self.placeholders[db] = self.databases[db].database.name
	@property
	def databases_gdx(self):
		return [db.database for db in self.databases.values()]

	@property
	def state(self):
		return self.setstate if self.setstate in self.conf.keys() else list(self.conf.keys())[0]

	def try_state(self,state):
		return self.conf[self.state] if state not in self.conf else self.conf[state]

	def get_conf(self,x):
		return self.conf[self.state][x]

	def set_conf(self,k,v):
		self.conf[self.state][k] = v

	def clean_g_exo(self,clean=True):
		if clean is True:
			[self.conf[k].__setitem__('g_exo',self.conf[k]['g_exo']-self.conf[k]['g_endo']) for k in self.conf.keys()];
		elif clean is False:
			self.set_conf('g_exo', self.get_conf('g_exo')-self.get_conf('g_endo'))

	###################################################################################################
	###										0: Pickling settings 									###
	###################################################################################################

	def init_ws_wfolder(self,work_folder):
		if isinstance(work_folder, gams.GamsWorkspace):
			self.ws = work_folder
			self.upd_work_folder()
		else:
			self.work_folder = os.getcwd() if work_folder is None else work_folder
			self.upd_workspace()

	def init_from_pickle(self,pickle_path,work_folder=None):
		with open(pickle_path, "rb") as file:
			pickled_data = pickle.load(file)
		self.update_with_ws(work_folder,pickled_data.__dict__)

	def update_with_ws(self,work_folder,dict_):
		self.__dict__ = {key: value for key,value in dict_.items() if key not in ('ws','work_folder','databases')}
		if work_folder is None and 'work_folder' in dict_:
			work_folder = dict_['work_folder']
		self.init_ws_wfolder(work_folder)
		self.databases = {}
		try:
			self.databases = {key: self.add_database(value) for key,value in dict_['databases'].items()}
		except KeyError:
			pass

	def reset_database(self,db,position=None):
		self.databases[db].database.__del__() # free up space
		self.databases[db].database = None
		position = list(self.databases.keys()).index(db) if position is None else position
		db_new = self.databases[db]
		self.databases.pop(db,None),self.placeholders.pop(db,None)
		self.add_database(db_new,position=position)
		return db_new.names

	def add_database(self,db,name=None,from_pickle=False,position=-1):
		if from_pickle is True:
			if name is None:
				database = DataBase.GPM_database(workspace=self.ws,pickle_path=db)
			else:
				database = DataBase.GPM_database(workspace=self.ws,pickle_path=db,**{'name':name})
		else:
			if name is None:
				database = DataBase.GPM_database(workspace=self.ws,db=db)
			else:
				database = DataBase.GPM_database(workspace=self.ws,db=db,**{'name':name})
		self.databases = insert_dict({database.name: database},self.databases,position=position)
		return database

	def __getstate__(self):
		if 'run_file' is not None and 'run_file' in self.export_settings['dropattrs']:
			self.files.pop(self.run_file,None)
		return {key:value for key,value in self.__dict__.items() if key not in self.export_settings['dropattrs']}

	def __setstate__(self,state):
		self.__dict__ = state
		[setattr(self,attr,self.std_settings()[attr]) for attr in self.export_settings['dropattrs'] if attr != 'ws'];

	def export(self,name=None,repo=None):
		name = self.name if name is None else name
		repo = self.data_folder if repo is None else repo
		with open(repo+'\\'+name, "wb") as file:
			pickle.dump(self,file)
		return repo+'\\'+name

	###################################################################################################
	###										1: Write methods			 							###
	###################################################################################################

	def write_collect_files(self,name):
		""" Write a file that collects other files with $import statements. 
			If 'name' in self.collect_files, modify name. If 'name' is the only one, do nothing."""
		out_str = ''
		if self.collect_files is None:
			for x in self.files:
				out_str += f"$IMPORT {x};\n"
			self.collect_files = OrdSet([name])
		else:
			if name in self.collect_files:
				if len(self.collect_files)==1:
					return out_str
				else:
					name = end_w_gms(DataBase.return_version(name.split('.gms')[0], [x.split('.gms')[0] for x in self.collect_files]))
			for x in self.collect_files:
				out_str += f"$IMPORT {x};\n"
			self.collect_files.add(name)
		return out_str

	def write_collect_and_run_file(self,name):
		out_str = ''
		if self.root_file is None:
			out_str += read_root()
		else:
			out_str += read_root(default=False,text=self.root_file)
		if self.collect_files is None:
			for x in self.files:
				out_str += f"$IMPORT {x};\n"
			if self.run_file not in self.files:
				if self.run_file is not None:
					out_str += f"$IMPORT {self.run_file};\n"
		else:
			for x in self.collect_files:
				out_str += f"$IMPORT {x};\n"
			if self.run_file not in self.collect_files:
				if self.run_file is not None:
					out_str += f"$IMPORT {self.run_file};\n"
		self.collect_file = name
		return out_str

	###################################################################################################
	###											2: Std.add				 							###
	###################################################################################################


class mgs:
	"""
	Collection of methods for merging gams_settings (classes) into one, to run combined models.
	"""
	@staticmethod
	def merge(ls,ws=None,merge_dbs_adhoc=True,name=None,run_file=None,solve=None,clean_exo=True):
		if ws is None:
			ws = ls[0].ws
		gs = gams_settings(work_folder=ws,**{'name':mgs.merge_names(ls,name=name),
													  'placeholders': mgs.merge_placeholders(ls),
													  'run_file': mgs.merge_run_files(ls,run_file),
													  'conf': mgs.merge_conf(ls,mgs.merge_names(ls,name=name),solve),
													  'files': mgs.merge_files(ls),
													  'collect_files': mgs.merge_collect_files(ls)})
		mgs.merge_databases(gs,ls,merge_dbs_adhoc)
		gs.clean_g_exo(clean=clean_exo)
		return gs

	@staticmethod
	def merge_conf(ls,name,solve):
		return {k: {'name': name+'_'+k,'g_endo': mgs.merge_g_endo(ls,k), 'g_exo': mgs.merge_g_exo(ls,k), 'blocks': mgs.merge_blocks(ls,k), 'solve': mgs.merge_run_files(ls,solve)} for s in ls for k in s.conf}
		
	@staticmethod
	def merge_names(ls,name):
		return '_'.join([s.name for s in ls]) if name is None else name

	@staticmethod
	def merge_databases(gs_merged,ls,merge_dbs_adhoc):
		"""
		Note that if dbs_adhoc is True the databases that share the same name are merged. 
		However, if symbols overlap in the various databases, these are merged as well. Thus 
		the underlying data may be altered as well. 
		"""
		if merge_dbs_adhoc is True:
			databases = {}
			for database_name in OrdSet([x for s in ls for x in s.databases]):
				db_temp = DataBase.GPM_database(workspace=gs_merged.ws,name=database_name)
				for database in [s.databases[x] for s in ls for x in s.databases if x==database_name]:
					DataBase.GPM_database.merge_dbs(db_temp.series,database,'first')
					databases[database_name] = db_temp
			gs_merged.databases = databases
		else:
			if len(OrdSet([x for s in ls for x in s.databases]))==len([x for s in ls for x in s.databases]):
				for s in ls:
					for db in s.databases.values():
						gs_merged.add_database(db)
			else:
				raise ValueError(f"Databases overlap in names. Consider setting merge_dbs_adhoc=True, or in another way handle database-overlap prior to merging settings.")
		
	@staticmethod
	def merge_placeholders(ls):
		return {key: value for s in ls for key,value in s.placeholders.items()}
	@staticmethod
	def merge_run_files(ls,run_file):
		return None if run_file is None else run_file
	@staticmethod
	def merge_blocks(ls,k):
		return OrdSet([x for y in ls for x in y.try_state(k)['blocks']])
	@staticmethod
	def merge_g_endo(ls,k):
		return OrdSet([x for y in ls for x in y.try_state(k)['g_endo']])
	@staticmethod
	def merge_g_exo(ls,k):
		return OrdSet([x for y in ls for x in y.try_state(k)['g_exo']])
	@staticmethod
	def merge_files(ls):
		return {key: value for s in ls for key,value in s.files.items()}
	@staticmethod
	def merge_collect_files(ls):
		return NoneIfAllNone(OrdSet([x for y in ls for x in iteNone(y.collect_files)]))

class gams_model_py:
	def __init__(self, pickle_path = None, gsettings = None, kwargs_gs = {}, **kwargs):
		""" Initialize from pickle or gsettings. The work_folder can be either a repository or a gams Workspace. """
		if pickle_path is not None:
			with open(pickle_path,"rb") as file:
				self.__dict__ = pickle.load(file).__dict__
				self.add_pklattrs(**kwargs)
		else:
			self.std_settings()
			if isinstance(gsettings, gams_settings):
				self.settings = gsettings
			else:
				self.settings = gams_settings(pickle_path=gsettings,**kwargs_gs)
		self.update_attrs(kwargs)

	def update_attrs(self,kwargs):
		for key,value in kwargs.items():
			setattr(self,key,value)

	def std_settings(self):
		self.name = "model_py"
		self.groups = {}
		self.exceptions = []
		self.exceptions_load = []
		self.components = {}
		self.export_files = None
		self.blocks = {}
		self.functions = None
		self.main_db = None
		self.import_settings = {}
		self.export_settings = {'dropattrs': ['settings'], 'pklattrs': {'settings': 'gams_settings'}}

	def export(self,name=None,repo=None):
		name = self.name if name is None else name
		repo = self.settings.data_folder if repo is None else repo
		with open(repo+'\\'+name, "wb") as file:
			pickle.dump(self,file)
		return repo+'\\'+name

	def __getstate__(self):
		for attr in self.export_settings['pklattrs']:
			self.import_settings[attr] = getattr(self,attr).export()
		return {key: value for key,value in self.__dict__.items() if key not in self.export_settings['dropattrs']}

	def add_pklattrs(self,**kwargs):
		for attr,pkl_path in self.import_settings.items():
			attr_class = eval(self.export_settings['pklattrs'][attr])
			setattr(self,attr,attr_class(pickle_path=pkl_path,**try_(kwargs,attr,)))

	@property
	def database(self):
		return self.settings.databases[self.main_db] if self.main_db is not None else list(self.settings.databases.values())[0]

	def default_placeholders(self):
		return {self.database.name: self.database.name}

	def run_default(self,repo=None,export_settings=False):
		if repo is None:
			repo = self.settings.data_folder
		if not os.path.exists(repo):
			os.makedirs(repo)
		self.write_default_components()
		self.default_export(repo,export_settings=export_settings)

	def write_default_components(self):
		write_to_db = [k for k,v in self.settings.databases.items() if v == self.database][0]
		self.functions = gams_model_py.merge_functions(regex_gms.functions_from_str(default_user_functions()),self.functions)
		self.components['functions'] = self.write_functions()
		self.components['sets'] = self.write_sets()
		self.components['alias'] = self.write_aliased_sets()
		self.components['sets_other'] = self.write_sets_other()
		self.components['sets_load'] = self.write_sets_load(write_to_db)
		self.components['parameters'] = self.write_parameters()
		self.components['parameters_load'] = self.write_parameters_load(write_to_db)
		self.components['groups'] = self.write_groups()
		self.components['groups_load'] = self.write_groups_load(write_to_db)
		self.components['blocks'] = self.write_blocks()

	@staticmethod
	def merge_functions(functions1,functions2):
		"""
		Merge two dictionaries with potentially overlapping keys; if keys are overlapping, keep values from dict = function1.
		"""
		if functions1 is None:
			return functions2
		elif functions2 is None:
			return functions1 
		else:
			return {**functions1,**{key: functions2[key] for key in OrdSet(functions2.keys())-OrdSet(functions1.keys())}}

	def default_export(self,repo,export_settings=False):
		self.export_components(self.default_files_components(repo))
		self.add_default_collect(self.settings.name+'_CollectFile.gms',repo)
		if export_settings:
			self.settings.export(repo,self.settings.name)

	def add_default_collect(self,name,repo):
		if self.settings.collect_files is None or not (name in self.settings.collect_files and len(self.settings.collect_files)==1):
			with open(repo+'\\'+end_w_gms(name),"w") as file:
				file.write(self.settings.write_collect_files(name))
		self.settings.files[end_w_gms(name)] = repo

	def default_files_components(self,repo):
		self.export_files = {self.settings.name+'_functions.gms': {'repo': repo, 'components': ['functions']},
							 self.settings.name+'_sets.gms': {'repo': repo, 'components': ['sets','alias','sets_other','sets_load']},
							 self.settings.name+'_parameters.gms': {'repo': repo, 'components': ['parameters','parameters_load']},
							 self.settings.name+'_groups.gms': {'repo': repo, 'components': ['groups','groups_load']},
							 self.settings.name+'_blocks.gms': {'repo': repo, 'components': ['blocks']}}
		return self.export_files

	def export_components(self,files,add_to_settings=True):
		"""
		Files is a dictionary where:
			keys = file names.
			dict[file]: Dictionary with keys = {'repo','components'}. 
		"""
		for x in files:
			with open(files[x]['repo']+'\\'+end_w_gms(x),"w") as file:
				[file.writelines(self.components[c]) for c in files[x]['components']];
			if add_to_settings:
				self.settings.files[end_w_gms(x)] = files[x]['repo']

	def add_group_to_groups(self,group,gname,merge=False):
		if merge is True:
			self.groups[gname] = group if gname not in self.groups else self.groups[gname]+group
		else:
			self.groups[gname] = group

	def write_sets(self):
		"""
		If there are no additional fundamental sets to be added → return ''
		If there are, declare them.
		"""
		if bool(OrdSet(self.database.sets['sets'])-OrdSet(self.database.get('alias_map2'))-OrdSet(self.exceptions)) is False:
			return ''
		else:
			out_str = 'sets\n'
			for x in (OrdSet(self.database.sets['sets'])-OrdSet(self.database.get('alias_map2'))-OrdSet(self.exceptions)):
				out_str += '\t'+self.database[x].write()+'\n'
			out_str = out_str+';\n\n'
			return out_str

	def write_aliased_sets(self):
		out_str = ''
		for x in OrdSet(self.database.get('alias_set'))-OrdSet(self.exceptions): # is the set itself in 'exceptions'?
			if bool(OrdSet(self.database.alias_dict[x])-OrdSet(self.exceptions)) is not False: # is the aliased sets in 'exceptions'?
				out_str += 'alias({x},{y});\n'.format(x=x,y=','.join(list(OrdSet(self.database.alias_dict[x])-OrdSet(self.exceptions)))) # write alias statement
		return out_str+'\n'

	def write_sets_other(self):
		if bool(OrdSet(self.database.sets_flat)-OrdSet(self.database.sets['sets'])-OrdSet(self.exceptions)) is False:
			return ''
		else:
			out_str = 'sets\n'
			for x in (OrdSet(self.database.sets_flat)-OrdSet(self.database.sets['sets'])-OrdSet(self.exceptions)):
				out_str += '\t'+self.database[x].write()+'\n'
			out_str = out_str+';\n\n'
			return out_str

	def write_sets_load(self,gdx,onmulti=True):
		if bool(OrdSet(self.database.sets_flat)-OrdSet(self.exceptions_load)-OrdSet(self.database.get('alias_map2'))) is False:
			return ''
		else:
			out_str = '$GDXIN %'+gdx+'%\n'
			if onmulti:
				out_str += '$onMulti\n'
			for x in OrdSet(self.database.sets['sets'])-OrdSet(self.exceptions_load)-OrdSet(self.database.get('alias_map2')):
				out_str += '$load '+x+'\n'
			for x in OrdSet(self.database.sets['subsets'])-OrdSet(self.exceptions_load)-OrdSet(self.database.get('alias_map2')):
				out_str += '$load '+x+'\n'
			for x in OrdSet(self.database.sets['mappings'])-OrdSet(self.exceptions_load):
				out_str += '$load '+x+'\n'
			out_str += '$GDXIN\n'
			if onmulti:
				out_str += '$offMulti\n'
			return out_str

	def write_parameters(self):
		if bool(OrdSet(self.database.parameters_flat)-OrdSet(self.exceptions)) is False:
			return ''
		else:
			out_str = 'parameters\n'
			for x in (OrdSet(self.database.parameters_flat)-OrdSet(self.exceptions)):
				out_str += '\t'+self.database[x].write()+'\n'
			out_str += ';\n\n'
		return out_str

	def write_parameters_load(self,gdx,onmulti=True):
		if bool(OrdSet(self.database.parameters_flat)-OrdSet(self.exceptions_load)) is False:
			return ''
		else:
			out_str = '$GDXIN %'+gdx+'%\n'
			if onmulti:
				out_str += '$onMulti\n'
			for x in OrdSet(self.database.parameters_flat)-OrdSet(self.exceptions_load):
				out_str += '$load '+x+'\n'
			if onmulti:
				out_str += '$offMulti\n'
			return out_str

	def write_blocks(self):
		out_str = ''
		for block in self.blocks:
			out_str += self.write_block(block)
		return out_str

	def write_block(self,block):
		return f"$BLOCK {block} \n\t{self.blocks[block]}\n$ENDBLOCK\n"

	def write_groups(self):
		out_str = ''
		for group in self.groups:
			out_str += self.write_group(group)
		return out_str

	def write_group(self,group):
		out_str = '$GROUP '+group+'\n'
		return '$GROUP '+group+'\n'+add_group(self.groups[group],self.database)+';\n\n'

	def write_groups_load(self,gdx):
		out_str = ''
		for group in self.settings.get_conf('g_endo'):
			out_str += self.write_group_load(group,gdx,level='level')
		for group in OrdSet(self.groups.keys())-OrdSet(self.settings.get_conf('g_endo')):
			out_str += self.write_group_load(group,gdx)
		return out_str

	def write_group_load(self,group,gdx,level='fixed'):
		if level=='fixed':
			out_str = '@load_fixed({group},%qmark%%{gdx}%");\n'.format(group=group,gdx=gdx)
		elif level=='level':
			out_str = '@load_level({group},%qmark%%{gdx}%");\n'.format(group=group,gdx=gdx)
		return out_str

	def write_functions(self):
		out_str = ''
		if self.functions is not None:
			for func in self.functions:
				out_str += self.functions[func]+'\n\n'
		return out_str
