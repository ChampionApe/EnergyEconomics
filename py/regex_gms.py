import re

def functions_from_file(file):
	with open(file) as infile:
		r = infile.read()
	return functions_from_str(r)
def blocks_from_file(file):
	with open(file) as infile:
		r = infile.read()
	return blocks_from_str(r)
def groups_from_file(file):
	with open(file) as infile:
		r = infile.read()
	return groups_from_str(r)

def functions_from_str(string):
	a = re.findall(r"^.*?\$FUNCTION(.*?)\$ENDFUNCTION.*?$",string,re.IGNORECASE | re.DOTALL | re.MULTILINE)
	if a:
		b = ['$FUNCTION' + a[i] + '$ENDFUNCTION' for i in range(len(a))]
		return {function_name_from_str(b[i]): b[i] for i in range(len(b))}
	else:
		return ''
def blocks_from_str(string):
	a = re.findall(r"^.*?\$BLOCK(.*?)\$ENDBLOCK.*?$",string,re.IGNORECASE | re.DOTALL | re.MULTILINE)
	if a:
		return [block_name_from_str('$BLOCK'+a[i] +'$ENDBLOCK') for i in range(len(a))]
	else:
		return []
def groups_from_str(string):
	a = re.findall(r"^.*?\$GROUP(.*?)\;.*?$",string,re.IGNORECASE | re.DOTALL | re.MULTILINE)
	if a:
		return [group_name_from_str('$GROUP'+a[i] +';') for i in range(len(a))]
	else:
		return []


def function_name_from_str(string):
	return re.search(r"^.*?\$FUNCTION(.*?)\(.*?",string,re.IGNORECASE | re.DOTALL | re.MULTILINE).group(1).strip()
def block_name_from_str(string):
	return re.search(r"^.*?\$BLOCK\s(.*?)\s.*?",string,re.IGNORECASE | re.DOTALL | re.MULTILINE).group(1).strip()		
def group_name_from_str(string):
	return re.search(r"^.*?\$GROUP\s(.*?)\s.*?",string,re.IGNORECASE | re.DOTALL | re.MULTILINE).group(1).strip()		

def lines_to_string(lines):
	out_str = ''
	for i in range(len(lines)):
		out_str += lines[i]
	return out_str

# replace var with sum:
def reduce_dim_with_map(setname,alias,mapname,varname,string,patterns=['equation','level','fixed','lower','upper']):
	"""
	Replace a variable in gms code as follows:
	(1) Identify all statements in string where the variable 'varname' enters,
	(2) check if 'setname' is in the domains of the relevant entry of 'varname',
	(3) if it is replace 'varname[setname,oth_domains]' with 'sum(alias$(mapname[setname,alias]), varname[alias,oth_domains])'.
	"""
	out = ''
	for x in [y for z in identify_var(varname,string) for y in identify_var(varname,string)[z]]:
		out += string.split(x,maxsplit=1)[0]
		if setname in domains_from_gms(x):
			out += f" sum({alias}$({mapname}[{setname},{alias}]), {x.split('[')[0]}{replace_domain(x,setname,alias)})"
		else:
			out += x
		string = string.split(x,maxsplit=1)[-1]
	out += string
	return out

def replace_domain(string,old,new):
	"""
	'string': section of code with one variable in it, including its domains.
	'old': name of domain that we wish to replace.
	'new': name of new domain. 
	"""
	return '['+', '.join([x if x!=old else new for x in domains_from_gms(string)])+']'

def domains_from_gms(string):
	return [x.strip() for x in re.search(r"\[(.*?)\]",string).group(1).split(',')]

def identify_var(varname,string,patterns=['equation','level','fixed','lower','upper']):
	"""
	Identify lists with patterns where the variable enters. 
	"""
	std_pattern =  {'equation': '[ \t(.*]{name}\[.*?\]', 
					'level': 	'[ \t(.*]{name}.l\[.*?\]',
					'fixed': 	'[ \t(.*]{name}.fx\[.*?\]',
					'lower': 	'[ \t(.*]{name}.lo\[.*?\]',
					'upper': 	'[ \t(.*]{name}.up\[.*?\]'}
	out = {pattern: [] for pattern in patterns}
	for x in std_pattern:
		if x in patterns:
			out[x] = re.findall(r'{pattern}'.format(pattern=std_pattern[x].format(name=varname)),string,flags=re.IGNORECASE)
	return out