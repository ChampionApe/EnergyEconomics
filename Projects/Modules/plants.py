from gmspython import *

class plants(gmspython):
	def __init__(self,pickle_path=None,work_folder=None,kwargs_ns={},**kwargs_gs):
		super().__init__(module='plants',pickle_path=pickle_path,work_folder=work_folder,**kwargs_gs)
