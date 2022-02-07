import DataBase,os,pandas as pd, numpy as np, gams, pickle
from dreamtools.gamY import Precompiler
from dreamtools import gams_pandas

def insert_dict(ndict,odict,position=0):
	return {**{k:odict[k] for k in list(odict.keys())[:position]},**ndict,**{k:odict[k] for k in list(odict.keys())[position:]}}

def database_type(database):
	if isinstance(database,str):
		return DataBase.py_db(file_path=database)
	elif isinstance(database,GamsDatabase):
		return DataBase.py_db(database_gdx=database)
	elif isinstance(database,DataBase.py_db):
		return database

def end_w_y(x,y):
	if x.endswith(y):
		return x
	else:
		return x+y
def end_w_opt(x):
	return end_w_y(x,'.opt')
def end_w_gdx(x):
	return end_w_y(x,'.gdx')
def end_w_gms(x):
	return end_w_y(x,'.gms')
def end_w_pkl(x):
	return end_w_y(x,'.pkl')


def read_root(default=True,file=False,text=False):
	if default:
		return default_Root()
	elif file is not False:
		with open(file,"r") as file:
			return file.read()
	elif text is not False:
		return text

def read_user_functions(default=True,file=False,text=False):
	if default:
		return default_user_functions()
	elif file is not False:
		with open(file,"r") as file:
			return file.read()
	elif text is not False:
		return text

def add_or_replace_code(part,string,**kwargs):
	if string in kwargs:
		if 'replace' in kwargs[string]:
			out += kwargs[string]['replace']
		else:
			out += part
		if 'add' in kwargs[string]:
			out += kwargs[string]['add']
		return out
	else:
		return part

def run_text(g_exo=None,g_endo=None,name=None,blocks=None,solvestat=False,solve='',**kwargs):
	out = '' if 'first' not in kwargs else kwargs['first']
	out += add_or_replace_code(fix(g_exo),'g_exo',**kwargs)
	out += add_or_replace_code(unfix(g_endo),'g_endo',**kwargs)
	out += add_or_replace_code(model_blocks(name,blocks),'blocks',**kwargs)
	if name is not None:
		out += f"""{name}.optfile=1;"""+'\n'
	if solvestat is True:
		out += add_solvestat(name)
	out += add_or_replace_code(default_solve(name,solve),'solve',**kwargs)
	if solvestat is True:
		out += update_solvestat(name)
	out += '' if 'end' not in kwargs else kwargs['end']
	return out

def fix(g_exo):
	return '' if g_exo is None else "$FIX {gnames};\n".format(gnames=', '.join(g_exo))
def unfix(g_endo):
	return '' if g_endo is None else "$UNFIX {gnames};\n".format(gnames=', '.join(g_endo))
def model_blocks(name,blocks):
	return '' if blocks is None else "$Model {mname} {blocks_text};\n".format(mname=name, blocks_text=', '.join(blocks))
def add_solvestat(model):
	return f"""scalars {model}_modelstat, {model}_solvestat;"""+'\n'
def update_solvestat(model):
	return f"""{model}_modelstat = {model}.modelstat; {model}_solvestat = {model}.solvestat;"""+'\n'
def default_solve(model,solve):
	return f"""solve {model} using CNS;"""+'\n' if solve is None else solve
def default_Root():
	return """# Root File for model
OPTION SYSOUT=OFF, SOLPRINT=OFF, LIMROW=0, LIMCOL=0, DECIMALS=6;
$SETLOCAL qmark ";
"""

def default_user_functions():
	return """
# User defined functions:
$FUNCTION load_level({group}, {gdx}):
  $offlisting
  $GROUP __load_group {group};
  $LOOP __load_group:
    parameter load_{name}{sets} "";
    load_{name}{sets}$({conditions}) = 0;
  $ENDLOOP
  execute_load {gdx} $LOOP __load_group: load_{name}={name}.l $ENDLOOP;
  $LOOP __load_group:
    {name}.l{sets}$({conditions}) = load_{name}{sets};
  $ENDLOOP
  $onlisting
$ENDFUNCTION
$FUNCTION load_fixed({group}, {gdx}):
  $offlisting
  $GROUP __load_group {group};
  $LOOP __load_group:
    parameter load_{name}{sets} "";
    load_{name}{sets}$({conditions}) = 0;
  $ENDLOOP
  execute_load {gdx} $LOOP __load_group: load_{name}={name}.l $ENDLOOP;
  $LOOP __load_group:
    {name}.fx{sets}$({conditions}) = load_{name}{sets};
  $ENDLOOP
  $onlisting
$ENDFUNCTION
"""

def default_opt(ws,string=None,name="options.opt"):
	opt = ws.add_options()
	opt.all_model_types = "CONOPT4" # use solver
	file = open(os.path.join(ws.working_directory, name), "w") # open options file and write:
	if string is None:
		file.write("\
			# Tell the solver that the system is square \n\
			# lssqrs = t \n\
			\n\
			# Keep searching for a solution even if a bound is hit (due to non linearities) \n\
			lmmxsf = 1 \n\
			\n\
			# Time limit in seconds \n\
			rvtime = 1000000 \n\
			reslim = 1000000 \n\
			\n\
			# Limit for slow progress, Range: [12,MAXINT], Default: 12 \n\
			# lfnicr = 100 \n\
			\n\
			# Optimality tolerance for reduced gradient \n\
			#  RTREDG = 1.e-9 \n\
			\n\
			# Absolute pivot tolerance, Range: [2.2e-16, 1.e-7], Default: 1.e-10 \n\
			# rtpiva = 2.22044605e-16 \n\
			Threads = 4 \n\
			THREADF=4 \n\
			")
	else: 
		file.write(string)
	file.close()
	opt.file = 1
	return opt
