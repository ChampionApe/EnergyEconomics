import os, pandas as pd, numpy as np, DataBase, gams
from dreamtools.gamY import Precompiler
from DB2Gams_l2 import gams_model_py, gams_settings

def append_index_with_1dindex(index1,index2):
	"""
	index1 is a pandas index/multiindex. index 2 is a pandas index (not multiindex).
	Returns a pandas multiindex with the cartesian product of elements in (index1,index2). 
	NB: If index1 is a sparse multiindex, the cartesian product of (index1,index2) will keep this structure.
	"""
	return pd.MultiIndex.from_tuples([a+(b,) for a in index1 for b in index2],names=index1.names+index2.names) if isinstance(index1,pd.MultiIndex) else pd.MultiIndex.from_tuples([(a,b) for a in index1 for b in index2],names=index1.names+index2.names)

def prepend_index_with_1dindex(index1,index2):
	return pd.MultiIndex.from_tuples([(b,)+a for a in index1 for b in index2],names=index2.names+index1.names) if isinstance(index1,pd.MultiIndex) else pd.MultiIndex.from_tuples([(b,a) for a in index1 for b in index2],names=index2.names+index1.names)

def add_grid_to_series(vals_init,vals_end,linspace_index,name,gridtype='linear',phi=1,scalar=False):
	"""
	vals_init and vals_end are pandas series defined over a common index.
	linspace_index is a pandas index of the relevant length of the desired linspace.
	The function returns a pandas series with a gridtype-spaced grid added to each element i in vals_init/vals_end.
	"""
	if gridtype=='linear':
		apply_grid = lambda x0,xN,N: np.linspace(x0,xN,num=N)
	elif gridtype=='rust':
		apply_grid = lambda x0,xN,N: rust_space(x0,xN,N,phi)
	elif gridtype=='pol':
		apply_grid = lambda x0,xN,N: pol_space(x0,xN,N,phi)
	if scalar is False:
		return pd.concat([pd.Series(apply_grid(vals_init.values[i],vals_end.values[i],len(linspace_index)), index = append_index_with_1dindex(vals_init.index[vals_init.index.isin([vals_init.index[i]])],linspace_index),name=name) for i in range(len(vals_init))])
	elif scalar is True:
		return pd.Series(apply_grid(vals_init,vals_end,len(linspace_index)),index = linspace_index,name=name)

def add_linspace_to_series(vals_init,vals_end,linspace_index,name):
	return pd.concat([pd.Series(np.linspace(vals_init.values[i],vals_end.values[i],num=len(linspace_index)),index = append_index_with_1dindex(vals_init.index[vals_init.index.isin([vals_init.index[i]])],linspace_index),name=name) for i in range(len(vals_init))])

def rust_space(x0,xN,N,phi):
	x = np.empty(N)
	x[0] = x0
	for i in range(2,N+1):
		x[i-1] = x[i-2]+(xN-x[i-2])/((N-i+1)**phi)
	return x

def pol_space(x0,xN,N,phi):
	return np.array([x0+(xN-x0)*((i-1)/(N-1))**phi for i in range(1,N+1)])

def end_w_y(x,y):
	if x.endswith(y):
		return x
	else:
		return x+y
def end_w_gdx(x):
	return end_w_y(x,'.gdx')
def end_w_gms(x):
	return end_w_y(x,'.gms')
def end_w_gmy(x):
	return end_w_y(x,'.gmy')

def nl(var,loop_name,subset=None):
	return var+'_'+loop_name if subset is None else var+'_'+loop_name+'_subset'

def sneaky_db(db0,db_star,diff=False,shock_name='shock',n_steps=10,loop_name='l1',update_variables='all',clean_up = True, gridtype='linear',phi=1,error=1e-11,**kwargs):
	shock_db = DataBase.GPM_database(workspace=db0.workspace,alias=db0.get('alias_'),**{'name': shock_name})
	shock_db[loop_name] = loop_name+'_'+pd.Index(range(1,n_steps+1),name=loop_name).astype(str)
	if update_variables=='all':
		update_variables = [var for var in db0.variables_flat if var in db_star.variables_flat];
	for var in set(update_variables).intersection(set(db0.variables['variables'])):
		common_index = db_star.get(var).index.intersection(db0.get(var).index)
		symbol_star,symbol0 = db_star.get(var)[db_star[var].index.isin(common_index)], db0.get(var)[db0[var].index.isin(common_index)]
		if diff is True:
			common_index = symbol_star[abs(symbol_star-symbol0)>error].index
			symbol_star,symbol0 = symbol_star[symbol_star.index.isin(common_index)], symbol0[symbol0.index.isin(common_index)]
		if not symbol_star.empty:
			shock_db[nl(var,loop_name,subset=True)] = symbol_star.index
			shock_db[nl(var,loop_name)] = DataBase.gpy_symbol(add_grid_to_series(symbol0.sort_index(), symbol_star.sort_index(), shock_db.get(loop_name), nl(var,loop_name),gridtype=gridtype,phi=phi),**{'gtype': 'parameter'})
	for var in set(update_variables).intersection(set(db0.variables['scalar_variables'])):
		if diff is True and (abs(db0.get(var)-db_star.get(var))>error):
			pass
		else:
			shock_db[nl(var,loop_name,subset=True)] = shock_db.get(loop_name)
			shock_db[nl(var,loop_name)] = DataBase.gpy_symbol(add_grid_to_series(db0.get(var),db_star.get(var),shock_db.get(loop_name),nl(var,loop_name),gridtype=gridtype,phi=phi,scalar=True),**{'gtype':'parameter'})
	shock_db.update_all_sets(clean_alias=True)
	shock_db.merge_internal()
	return shock_db,{'shock_name': shock_name, 'n_steps': n_steps, 'loop_name': loop_name, 'update_variables': update_variables, 'clean_up': clean_up, 'gridtype': gridtype, 'phi': phi}

def simple_shock_db(vals_target,db0,n_steps=10,shock_name='shock',loop_name='l1',gridtype='linear',phi=1):
	loop = pd.Index(range(1,n_steps+1),name=loop_name).astype(str)
	db_star = DataBase.GPM_database(workspace=db0.workspace,**{'name':shock_name})
	db_star[vals_target.name] = vals_target
	shock_db = sneaky_db(db0,db_star,shock_name=shock_name,n_steps=n_steps,loop_name=loop_name,gridtype=gridtype,phi=phi)[0]
	return shock_db

class AddShocks:
	"""
	Class that includes various ways to write gams-files that adds shocks to a GAMS model.
	"""
	def __init__(self,name,shock_db,loop_name,work_folder=None,prefix='sol_'):
		self.name = name # name of model to 'solve' in loop statement.
		self.shock_gm = gams_model_py(gsettings=gams_settings(work_folder=work_folder)) # gams_model_py class with information on shocks. 
		self.shock_gm.settings.add_database(shock_db)
		self.loop_name = loop_name # name of mapping to loop over.
		self.loop_text = "" # text to write inside loop.
		self.prefix=prefix # prefix used in UEVAS part.
		self.write_components = {} # components used to write 'text'.

	def WriteResolve(self,type_='CNS',solvetext=None):
		return f"solve {self.name} using {type_};\n" if solvetext is None else solvetext

	@property
	def text(self):
		"""
		Return loop state with current state of attributes. 
		"""
		return ' '.join([self.write_components[x] for x in self.write_components])

	def write_sets(self):
		"""
		Write gams code for declaring loop-sets, and loading in values form database in self.shock_gm.database.
		"""
		self.write_components['sets'] = (self.shock_gm.write_sets()+
										self.shock_gm.write_aliased_sets()+
										self.shock_gm.write_sets_other()+
										self.shock_gm.write_sets_load(self.shock_gm.database.name))
		return self.write_components['sets']

	def write_pars(self):
		"""
		Write gams code for declaring parameters and load in values.
		"""
		self.write_components['pars'] = (self.shock_gm.write_parameters()+
										 self.shock_gm.write_parameters_load(self.shock_gm.database.name))
		return self.write_components['pars']

	def write_loop_text(self):
		"""
		Write the loop text using the database with loop information + text from 'loop_text'.
		"""
		self.write_components['loop'] = """loop( ({sets}){cond}, {loop})
		""".format( sets = ', '.join(self.shock_gm.database[self.loop_name].index.names),
					cond = '$('+self.shock_gm.database[self.loop_name].write()+')' if self.shock_gm.database[self.loop_name].write()!=self.loop_name else '',
					loop = self.loop_text)
		return self.write_components['loop']

	def UpdateExoVarsAndSolve(self,model,model_name=None,solvetext=None):
		"""
		(Shorthand: UEVAS, could in principle be a class.)
		Write a type of 'loop-text' that performs the following steps:
			(1) Update value of exogenous variable,
			(2) Resolve model,
			(3) Store solution in database.
		"""
		self.model = model
		self.name = self.model.settings.get_conf('name') if model_name is None else model_name
		self.solvetext = solvetext
		self.UEVAS = {'sol': {}, 'adj': {}}

	@property
	def UEVAS_text(self):
		self.write_components = {}
		self.write_sets()
		self.write_pars()
		if len(self.UEVAS['sol'])>0:
			self.UEVAS_WritePGroup()
		self.loop_text = self.UEVAS_UpdateExoVars()+self.WriteResolve(solvetext=self.solvetext)+self.UEVAS_WriteStoreSol()
		self.write_loop_text()
		return self.text

	def UEVAS_2gmy(self,file_name):
		with open(end_w_gms(file_name),"w") as file:
			file.write(self.UEVAS_text)
		with open(end_w_gmy(file_name),"w") as file:
			file.write(Precompiler(end_w_gms(file_name))())
		# os.remove(end_w_gms(file_name))
		self.gmy = end_w_gmy(file_name)
		self.gms = end_w_gms(file_name)

	def UEVAS_var2sol(self,var,loop_dom,conditions=None):
		self.UEVAS['sol'][DataBase.return_version(self.prefix+var,self.UEVAS['sol'])] = 	{'dom': f"[{', '.join(self.shock_gm.database.get(loop_dom).names+self.model.out_db[var].index.names)}]",
											 		 										'cond': "" if conditions is None else f"$({conditions})",
											  		 										'var': var}
	def UEVAS_WritePGroup(self):
		self.write_components['UEVAS_sol'] = 'parameter\n'
		for x in self.UEVAS['sol']:
			self.write_components['UEVAS_sol'] += f"\t{x}{self.UEVAS['sol'][x]['dom']}\n" # add conditionals to param? {self.UEVAS['sol'][x]['cond']}
		self.write_components['UEVAS_sol'] += ';\n\n'

	def UEVAS_WriteStoreSol(self):
		out_str = ""
		for x in self.UEVAS['sol']:
			out_str += "{solpar} = {solvar};\n".format(
						  solpar = x+self.UEVAS['sol'][x]['dom']+self.UEVAS['sol'][x]['cond'],
						  solvar = (self.model.out_db[self.UEVAS['sol'][x]['var']].write(l='.l')))
		out_str += '\n'
		return out_str

	def UEVAS_adjVar(self,var,par,conditions=None,overwrite=False):
		self.UEVAS['adj'][DataBase.return_version(var,self.UEVAS['adj'])] = {'varname': var, 'par': par, 'cond': conditions}

	def UEVAS_UpdateExoVars(self):
		out_str = "" 
		for x in self.UEVAS['adj']:
			out_str += "\t{var} = {par};\n".format(
							var = self.model.out_db[self.UEVAS['adj'][x]['varname']].write(conditions=self.UEVAS['adj'][x]['cond'],l='.fx'),
							par = self.shock_gm.database[self.UEVAS['adj'][x]['par']].write())
		out_str += '\n\n'
		return out_str
