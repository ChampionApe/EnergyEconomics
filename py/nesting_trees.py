import pandas as pd, DataBase, DataBase_wheels
from excel2py import xl2PM

def df(x,kwargs):
	"""
	Modify x using kwargs.
	"""
	return x if x not in kwargs else kwargs[x]

class nt:
	"""
	Small class of nesting trees
	"""
	def __init__(self,tree_name="",tree=None,kwargs_database={},**kwargs):
		self.name= tree_name
		self.tree=tree
		self.type_io = 'input'
		self.version = 'std'
		self.n = 'n'
		self.nn = 'nn'
		self.nnn = 'nnn'
		self.map_ = 'map_'+self.name # map branches to knots
		self.kno = 'kno_'+self.name # knots 
		self.bra = 'bra_'+self.name # branches
		self.inp = 'inp_'+self.name # inputs: Branch, not knot
		self.out = 'out_'+self.name # outputs: Knot, not branch.
		self.temp_namespace = None # Dictionary/mapping that can be applied to pandas indices.
		self.update(kwargs)
		if self.type_io=='input' and 'type_f' not in kwargs:
			self.type_f = 'CES' # set default type to ces
		elif self.type_io=='output' and 'type_f' not in kwargs:
			self.type_f = 'CET' # set default type to cet
		self.database = DataBase.GPM_database(alias=pd.MultiIndex.from_tuples([(self.n, self.nn), (self.n, self.nnn)]),**{**{'name': self.name},**kwargs_database})

	def apply_namespace(self):
		if self.temp_namespace is not None:
			return DataBase_wheels.small_updates.set_values(self.database,self.n,self.temp_namespace)

	def run_all(self,Q2P=None,**kwargs):
		self.mapping_from_tree()
		self.set_from_tree()
		self.knots_from_tree()
		self.branches_from_tree()
		self.inputs_from_tree()
		self.outputs_from_tree()
		self.database.update_aliased_sets(ign_alias=False)
		if self.version =='Q2P':
			self.version_Q2P(Q2P,**kwargs)
		self.apply_namespace()

	def mapping_from_tree(self):
		temp = []
		for key in self.tree:
			temp += [(value,key) for value in self.tree[key]]
		self.database[self.map_] = pd.MultiIndex.from_tuples(temp,names=[self.n,self.nn])
		self.database[self.map_].name = self.map_

	def set_from_tree(self):
		temp = []
		for key in self.tree:
			temp += self.tree[key]+[key]
		self.database[self.n] = pd.Index(temp,name=self.n).unique()

	def knots_from_tree(self):
		self.database[self.kno] = pd.Index(set(self.database.get(self.map_).get_level_values(1)),name=self.n)

	def branches_from_tree(self):
		self.database[self.bra] = pd.Index(set(self.database.get(self.map_).get_level_values(0)),name=self.n)

	def inputs_from_tree(self):
		self.database[self.inp] = pd.Index(set(self.database.get(self.map_).get_level_values(0))-set(self.database.get(self.map_).get_level_values(1)),name=self.n)

	def outputs_from_tree(self):
		self.database[self.out] = pd.Index(set(self.database.get(self.map_).get_level_values(1))-set(self.database.get(self.map_).get_level_values(0)),name=self.n)

	def update(self,kwargs):
		for key,value in kwargs.items():
			setattr(self,key,value)

	@staticmethod
	def tree_from_mu(mu):
		return {x: mu.index.get_level_values(0)[mu.index.get_level_values(1)==x].to_list() for x in mu.index.get_level_values(1).unique()}

	def version_Q2P(self,q2p,q2pname=None,q2p_agg_name =None,OnlyQname=None):
		"""
		Adjusts the tree to a version where prices and quantities are not defined over the same sets.
		A mapping q2p indicates a subset of q-elements, that are essentially the same, and thus they face the same price. 
		The following adjustments are made:
			- q2p are added to the database, as well as its name (mapping).
			- The aggregates that q-elements are mapped to are defined.
			- Create new subset of elements, that prices are not defined over (q-part).
			- Update inputs to include the elements from the q2p mapping (p-part).
			- The mapping q2p are automatically updated to include '(x,x)' mappings, in case the (p,q) sets are overlapping.
			- Update the set of all elements in the sector, to include the (potentially) new ones from q2p. 
			- Add the new elements that prices are defined over to 'inputs'.
			- Update 'version' of tree (default is 'std') to 'QPS'.
		"""
		self.q2p = 'q2p_'+self.name if q2pname is None else q2pname 
		self.q2p_agg = 'q2p_agg_'+self.name if q2p_agg_name is None else q2p_agg_name 
		self.OnlyQ = 'OnlyQ_'+self.name if OnlyQname is None else OnlyQname # name of subset with only Q defined over it - not P.
		self.database[self.q2p_agg] = pd.Index(q2p.get_level_values(1).unique(), name=self.n) # add aggregate part.
		self.database[self.inp] = pd.Index(set(self.database.get(self.inp)) - set(q2p.get_level_values(0)), name =self.n)
		self.database[self.OnlyQ] = pd.Index(q2p.get_level_values(0).unique(), name=self.n)
		self.database[self.inp] = pd.Index(set(self.database.get(self.inp)).union(set(q2p.get_level_values(1))), name=self.n)
		# Expand mapping n2nn with ('x'-'x') elements for overlapping combinations of the two sets (p,q):
		self.database[self.q2p] = q2p.union(pd.MultiIndex.from_tuples([(x,x) for x in set(self.database.get(self.n))-set(q2p.get_level_values(0))], names = [self.n, self.nn]))
		self.database[self.n] = pd.Index( self.database.get(self.n).union(
												self.database.get(self.q2p).get_level_values(0)).union(
												self.database.get(self.q2p).get_level_values(1)),
												name = self.n).unique()
		self.version='Q2P'

class tree_from_data(nt):
	"""
	Initialize tree from data, where data is the file-path for an excel file. 
	"""
	def __init__(self,data_path,sheet,sym_name='mu',rtype='vars',tree_name="",**kwargs):
		symbol = xl2PM.pm_from_workbook(data_path,{sheet:rtype})[sym_name]
		super().__init__(tree=nt.tree_from_mu(symbol),tree_name=tree_name,**{**{'n':symbol.domains[0], 'nn': symbol.domains[1]}},**kwargs)