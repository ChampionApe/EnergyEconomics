import openpyxl,io
import pandas as pd
from DataBase import *

class xl2PM:
	""" Collection of methods returning gpy_symbols from excel sheets. """
	@staticmethod
	def pm_from_workbook(workbook,read_sheets,name='pm_db',spliton='/'):
		"""	read_sheets should be a dict with keys = sheetnames, and value = type of function to read in. """
		if isinstance(workbook,str):
			with open(workbook,"rb") as file:
				in_mem_file = io.BytesIO(file.read())
			wb = openpyxl.load_workbook(in_mem_file,read_only=True,data_only=True)
		else:
			wb = workbook
		pm = PM_database(name=name)
		for sheet in read_sheets:
			GPM_database.merge_dbs(pm,PM_database(database=eval(f"xl2PM.{read_sheets[sheet]}(wb[sheet],spliton=spliton)")),'first')
		return pm

	@staticmethod
	def sets(sheet,**kwargs):
		""" Return a dictionary with keys = set names and values = gpy_symbols. na entries are removed. 
			The name of each set is defined as the first entry in each column. """
		pd_sheet = pd.DataFrame(sheet.values)
		return {pd_sheet.iloc[0,i]: gpy_symbol(pd.Index(pd_sheet.iloc[1:,i].dropna(),name=pd_sheet.iloc[0,i]),**{'name':pd_sheet.iloc[0,i]}) for i in range(pd_sheet.shape[1])}

	@staticmethod
	def subsets(sheet,spliton='/'):
		pd_sheet = pd.DataFrame(sheet.values)
		return {pd_sheet.iloc[0,i].split(spliton)[0]: gpy_symbol(pd.Index(pd_sheet.iloc[1:,i].dropna(),name=pd_sheet.iloc[0,i].split(spliton)[1]),**{'name': pd_sheet.iloc[0,i].split(spliton)[0]}) for i in range(pd_sheet.shape[1])}

	@staticmethod
	def maps(sheet,spliton='/'):
		pd_sheet = pd.DataFrame(sheet.values)
		pd_sheet.columns = [x.split(spliton)[0] for x in pd_sheet.iloc[0,:]]
		output = {}
		for col in set(pd_sheet.columns):
			pd_temp = pd_sheet[col]
			pd_temp.columns = [x.split(spliton)[1] for x in pd_temp.iloc[0,:]]
			index = pd.MultiIndex.from_frame(pd_temp.dropna().iloc[1:,:])
			index.name = col
			output[col] = gpy_symbol(index,**{'name': col})
		return output

	@staticmethod
	def pars(sheet,spliton='/'):
		return xl2PM.vars(sheet,spliton=spliton,gtype='parameter')

	@staticmethod
	def vars(sheet,spliton='/',gtype='variable'):
		""" If gtype='parameter' the series is added as parameter. """
		pd_sheet = pd.DataFrame(sheet.values)
		pd_sheet.columns = [x.split(spliton)[0] for x in pd_sheet.iloc[0,:]]
		output = {}
		for col in set(pd_sheet.columns):
			pd_temp = pd_sheet[col].dropna()
			pd_temp.columns = [x.split(spliton)[1] for x in pd_temp.iloc[0,:]]
			if pd_temp.shape[1]==2:
				index = pd.Index(pd_temp.iloc[1:,0])
			else:
				index = pd.MultiIndex.from_frame(pd_temp.iloc[1:,:-1])
			output[col] = gpy_symbol(pd.Series(pd_temp.iloc[1:,-1].values, index=index, name=col),**{'gtype': gtype})
		return output

	@staticmethod
	def vars_v2(sheet,ndim=2,gtype='variable',**kwargs):
		""" If param = True the series is added as a parameter."""
		pd_sheet = pd.DataFrame(sheet.values)
		index = pd.MultiIndex.from_frame(pd_sheet.iloc[1:,:ndim],names = pd_sheet.iloc[0,:ndim])
		df = pd.DataFrame(pd_sheet.iloc[1:,ndim:].values, index = index, columns = pd_sheet.iloc[0,ndim:])
		return {var: gpy_symbol(df[var].dropna()), **{'gtype':gtype}}

	@staticmethod
	def pars_v2(sheet,ndim=2,**kwargs):
		return xl2PM.vars_v2(sheet,ndim=ndim,gtype='parameter')

	@staticmethod
	def scalar_pars(sheet,**kwargs):
		return xl2PM.scalar_vars(sheet,gtype='parameter')

	@staticmethod
	def scalar_vars(sheet,gtype='variable',**kwargs):
		pd_sheet = pd.DataFrame(sheet.values)
		return {pd_sheet.iloc[i,0]: gpy_symbol(pd_sheet.iloc[i,1],**{'name':pd_sheet.iloc[i,0],'gtype':gtype}) for i in range(pd_sheet.shape[0])}

	@staticmethod
	def vars_2dmatrix(sheet,spliton='/',**kwargs):
		""" read in 2d variables arranged in matrix """
		pd_sheet = pd.DataFrame(sheet.values)
		domains = pd_sheet.iloc[0,0].split(spliton)
		var = pd.DataFrame(pd_sheet.iloc[1:,1:].values, index = pd.Index(pd_sheet.iloc[1:,0],name=domains[1]), columns = pd.Index(pd_sheet.iloc[0,1:], name = domains[2])).stack()
		var.name = domains[0]
		return {domains[0]: gpy_symbol(var,**kwargs)}

	@staticmethod
	def maps_2dmatrix(sheet,**kwargs):
		""" read in 2d maps arranged in matrix. 
			Along rows: Common index X. 
			Columns: Various other indices (Y) that are mapped to index X.
			Mappings are called X2Y."""
		pd_sheet = pd.DataFrame(sheet.values)
		pd_sheet.columns = pd_sheet.iloc[0,:]
		pd_sheet = pd_sheet.iloc[1:,:]
		common_index = pd_sheet.columns[0]
		output = {}
		for col in set(pd_sheet.columns)-set([common_index]):
			n = '2'.join([common_index,col])
			output[n] = pd.MultiIndex.from_frame(pd_sheet[[common_index,col]].dropna())
			output[n].name = n
		return output