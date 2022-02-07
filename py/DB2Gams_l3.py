from DB2Gams_l2 import *
import ShockFunction

class gams_model:
	def __init__(self,pickle_path=None,gsettings=None,opt_file=None,opt_file_name='conopt4',execute_name='CollectAndRun.gms',**kwargs):
		""" initialize gams model from path to pickle, gsettings ∈ {gams_settings,pickle_path} object."""
		if pickle_path is not None:
			with open(pickle_path, "rb") as file:
				self.__dict__ = pickle.load(file).__dict__
				self.add_pklattrs(**kwargs)
		else:
			self.execute_name = execute_name
			self.name = "gmodel" if 'gams_model_name' not in kwargs else kwargs['gams_model_name']
			if isinstance(gsettings, gams_settings):
				self.settings = gsettings
			else:
				self.settings = gams_settings(pickle_path=gsettings,**kwargs)
			self.export_settings = {'dropattrs': ['settings','opt','job'], 'pklattrs': {'settings': 'gams_settings'},'opt': opt_file if opt_file is not None else 'temp.opt'}
			self.add_options(opt_file=opt_file,name=opt_file_name)
			self.import_settings = {}

	def export(self,name=None,repo=None):
		name = self.name if name is None else name
		repo = self.settings.data_folder if repo is None else repo
		with open(repo+'\\'+name, "wb") as file:
			pickle.dump(self,file)
		return repo+'\\'+name

	def __getstate__(self):
		for attr in self.export_settings['pklattrs']:
			self.import_settings[attr] = getattr(self,attr).export()
		return {key: value for key,value in self.__dict__.items() if key not in dropattrs}

	def add_pklattrs(self,**kwargs):
		for attr,pkl_path in self.import_settings.items():
			attr_class = eval(self.export_settings['pklattrs'][attr])
			setattr(self,attr,attr_class(pickle_path=pkl_path,**try_(kwargs,attr)))

	def __setstate__(self,dict_):
		self.__dict__ = dict_
		self.add_options(opt_file=self.opt_file)

	def add_options(self,opt_file=None,name='conopt4'):
		if opt_file is None:
			self.opt = default_opt(self.ws,name=end_w_opt(name))
		else:
			self.opt = default_opt(self.ws,string=opt_file,name=end_w_opt(name))
		self.export_settings['opt'] = opt_file if opt_file is not None else end_w_opt(name)

	@property 
	def ws(self):
		return self.settings.ws

	@property 
	def work_folder(self):
		return self.ws.working_directory

	def setstate(self,state):
		self.settings.setstate = state
		if state not in self.settings.conf:
			self.settings.conf[state] = self.settings.std_configuration(state=state)

	@property
	def state(self):
		return self.model.settings.state

	def run(self,run_from_job=False,overwrite=False,kwargs_write={},options_add={},options_run={},kwargs_db={}):
		"""
		Create Model instance and run.
		"""
		if run_from_job is False:
			self.model_instance(overwrite=overwrite,**kwargs_write)
			self.add_job(options_add)
		self.run_job(options_run)
		self.out_db = DataBase.GPM_database(workspace=self.settings.ws,db=self.job.out_db,**kwargs_db)
		if self.settings.solvestat is True:
			self.modelstat = self.out_db.get(self.settings.get_conf('name')+'_modelstat')
			self.solvestat = self.out_db.get(self.settings.get_conf('name')+'_solvestat')

	def model_instance(self,add_default_placeholders=True,overwrite=False,**kwargs):
		if add_default_placeholders is True:
			self.settings.add_default_placeholders()
		self.update_placeholders()
		if self.settings.run_file is None:
			self.write_run_file(**kwargs)
		if self.settings.collect_file is None:
			self.write_collect_file()
		if overwrite is False:
			for file in self.settings.files:
				if not os.path.isfile(self.work_folder+'\\'+end_w_gms(file)):
					shutil.copy(self.settings.files[file]+'\\'+end_w_gms(file),self.work_folder+'\\'+end_w_gms(file))
		else:
			for file in OrdSet(self.settings.files.keys())-OrdSet([self.settings.run_file,self.execute_name]):
				if os.path.isfile(self.work_folder+'\\'+end_w_gms(file)):
					os.remove(self.work_folder+'\\'+end_w_gms(file))
				shutil.copy(self.settings.files[file]+'\\'+end_w_gms(file),self.work_folder+'\\'+end_w_gms(file))


	def add_job(self,options={}):
		"""
		Given a model_instance is created, this creates a GamsJob by compiling the self.model.collect_file
		usisng Precompiler from the dreamtools package. The GamsJob is added as an attribute self.job.
		"""
		self.compile_collect_file()
		self.job = self.ws.add_job_from_file(self.work_folder+'\\'+end_w_gms(self.settings.collect_file).replace('.gms','.gmy'),**options)
		return self.job

	def run_job(self,options={}):
		"""
		Add options using dict with key = option_name, value = option.
		"""
		self.job.run(gams_options=self.opt,databases=self.settings.databases_gdx,**options)

	def update_placeholders(self):
		"""
		Add placeholders to the options-file.
		"""
		[self.add_placeholder(placeholder,self.settings.placeholders[placeholder]) for placeholder in self.settings.placeholders];

	def add_placeholder(self,placeholder,name):
		"""	Add placeholder and what to substitue for the placeholder. """
		self.opt.defines[placeholder] = name

	def solve_sneakily(self,db_star=None,from_cp=False,cp_init=None,run_from_job=False,shock_db=None,options_run={},kwargs_shock={},kwargs_db={},model_name=None):
		if from_cp is False:
			cp_init = self.ws.add_checkpoint() if cp_init is None else cp_init
			self.run(run_from_job=run_from_job,options_run={**options_run,**{'checkpoint': cp_init}})
		if shock_db is None:
			(shock_db, kwargs_shock2) = ShockFunction.sneaky_db(self.out_db,db_star,**kwargs_shock)
		shock = self.std_UEVAS_from_db(shock_db,model_name=model_name,**{**kwargs_shock,**kwargs_shock2})
		self.execute_shock_from_cp(shock,cp_init,options_run=options_run,kwargs_db=kwargs_db)
		if self.settings.solvestat is True:
			return {'Modelstat': self.modelstat, 'Solvestat': self.solvestat}

	def std_UEVAS_from_db(self,shock_db,loop_name='l1',update_vars='all',shock_name='shock',store_sol={},model_name=None,solvetext=None,**kwargs):
		"""
		Creates a ShockFunction that loops over values in shock_db, for variables in update_vars.
		The shock_db needs to be arranged with variable names as var+'_loopval', and subsets var+'_subset' for the method to work.
		"""
		shock = ShockFunction.AddShocks('shock_'+self.settings.name if shock_name is None else shock_name,shock_db,loop_name,work_folder=self.work_folder)
		shock.UpdateExoVarsAndSolve(self,model_name=model_name,solvetext=solvetext)
		if update_vars=='all':
			update_vars = [par.split('_'+loop_name)[0] for par in shock_db.parameters['parameters']]
		for var in update_vars:
			shock.UEVAS_adjVar(var,ShockFunction.nl(var,loop_name),conditions=shock_db[ShockFunction.nl(var,loop_name,subset=True)].write())
		for var in store_sol:
			shock.UEVAS_var2sol(var,store_sol[var]['domains'],conditions=None if 'conditions' not in store_sol[var] else store_sol[var]['conditions'])
		shock.UEVAS_2gmy(self.work_folder+'\\'+shock.name)
		return shock

	def execute_shock_from_cp(self,shock,cp,options_run={},kwargs_db={}):
		self.settings.databases[shock.shock_gm.database.name] = shock.shock_gm.database
		self.opt.defines[shock.shock_gm.database.name] = shock.shock_gm.database.name+'.gdx'
		self.job = self.ws.add_job_from_file(shock.gms,**{'checkpoint': cp})
		self.run(run_from_job=True,options_run=options_run,kwargs_db=kwargs_db)

	def write_run_file(self,**kwargs):
		"""
		Writes a run_file for the code. This includes:
		(1) If a list of exogenous groups are included in the list self.model.g_exo, these are included in a $FIX statement.
		(2) If a list of endogenous groups are included in the list self.model.g_endo, these are included in an $UNFIX statement.
		(3) If a list of block names are included in the list self.model.blocks, these are used to define a model with name self.model.name.
		(4) If a specific solve statement is included in self.model.solve, this is used; otherwise a default solve statement is included.
		(5) Once the run_file has been written, the attribute is set to the new file name, and added to the dictionary of model instance files.
		NB: The kwargs are used to add gams code ad-hoc various places in the code, by specyfing after which element these should be inserted. 
		"""
		with open(self.work_folder+'\\'+'RunFile.gms', "w") as file:
			file.write(run_text(g_exo=self.settings.get_conf('g_exo'),g_endo=self.settings.get_conf('g_endo'),name=self.settings.get_conf('name'),blocks=self.settings.get_conf('blocks'),solvestat=self.settings.solvestat,solve=self.settings.get_conf('solve'),**kwargs))
		self.settings.run_file = 'RunFile.gms'
		self.settings.files['RunFile.gms'] = self.work_folder

	def compile_collect_file(self):
		with open(self.work_folder+'\\'+end_w_gms(self.settings.collect_file).replace('.gms','.gmy'), "w") as file:
			file.write(Precompiler(self.work_folder+'\\'+end_w_gms(self.settings.collect_file))())
		return self.work_folder+'\\'+end_w_gms(self.settings.collect_file).replace('.gms','.gmy')

	def write_collect_file(self):
		"""
		Writes a collect_file for the code. This includes:
		(1) The start of the code (root_file) can either be default (see read_root()), or the user can
			supply its own string in self.model.root_file (NB: A file option should be included here as well).
		(2) Then $IMPORT statements are included for all files in self.model.files (in the sequence they appear).
		(3) If the run_file is not included in the self.model.files, it is added in the end.
		(4) The attribute self.model.collect_file is updated to point to the collect_file.
		"""
		with open(self.work_folder+'\\'+self.execute_name, "w") as file:
			file.write(self.settings.write_collect_and_run_file(self.execute_name))

