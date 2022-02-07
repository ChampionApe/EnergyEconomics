import DataBase, pandas as pd

def df(x, kwargs):
    """	Modify x using keyword arguments (dicts,kwarg).	"""
    return x if x not in kwargs else kwargs[x]

def add_settings(version, kwargs_ns={}, kwargs_vals={}, **kwargs_oth):
    return eval(version)(kwargs_ns=kwargs_ns, kwargs_vals=kwargs_vals, **kwargs_oth)

class gs_v1:
    """ Settings for economic model, applied throughout all modules. 
            This class is used for a small open economy with exogenous long run interest rates, inflation rates and growth rates.
    """
    def __init__(self, kwargs_ns={}, kwargs_vals={}, dynamic=True, **kwargs_oth):
        self.dynamic = dynamic
        self.ns = {k: df(k, kwargs_ns) for k in self.LRP + self.time_ns}
        self.database = DataBase.PM_database()
        self.add_values(kwargs=kwargs_vals)

    @property
    def LRP(self):
        """ long run parameters for global model."""
        return ['R_LR', 'g_LR', 'infl_LR']

    @property 
    def time_ns(self):
        return ['t', 't0', 'tx0', 'tE', 'txE', 't0E', 'tx0E'] if self.dynamic is True else []

    def add_values(self,kwargs={}):
        """ Add the default values if not specified by kwargs."""
        for x in self.LRP:
            self.database[self.ns[x]] = DataBase.gpy_symbol(DataBase.kw_df(kwargs, x, self.default_values(x)), **{'gtype': 'parameter', 'text': self.default_text(x)})
        if self.dynamic is True:
        	self.add_time_to_database(kwargs=kwargs)
        	self.add_time_subsets_to_database()

    def default_values(self, var):
        if var == 'R_LR':
            return 1.03
        elif var == 'g_LR':
            return 0.02
        elif var == 'infl_LR':
            return 0.02

    def default_text(self, var):
        if var == 'R_LR':
            return 'Long run rate of interest, defined as 1+r.'
        elif var == 'g_LR':
            return 'Long run growth rate.'
        elif var == 'infl_LR':
            return 'Long run rate of inflation.'

    def add_time_to_database(self,kwargs={}):
    	if 't' in kwargs:
    		self.database[self.ns['t']] = pd.Index(kwargs['t'],name=self.ns['t'])
    	else:
    		tbounds = (1,3) if 'tbounds' not in kwargs else kwargs['tbounds']
    		self.database[self.ns['t']] = pd.Index(range(tbounds[0],tbounds[1]+1),name=self.ns['t'])

    def add_time_subsets_to_database(self):
    	""" Add time subsets"""
    	t_ints = self.get('t').astype(int).sort_values()
    	self.database[self.ns['t0']] = t_ints[t_ints==t_ints[0]]
    	self.database[self.ns['tE']] = t_ints[t_ints==t_ints[-1]]
    	self.database[self.ns['tx0']] = t_ints[t_ints != t_ints[0]]
    	self.database[self.ns['txE']] = t_ints[t_ints != t_ints[-1]]
    	self.database[self.ns['t0E']] = self.get('t0').union(self.get('tE'))
    	self.database[self.ns['tx0E']] = t_ints[~t_ints.isin(self.get('t0').union(self.get('tE')))]

    def g(self,symbol):
    	""" retrieve symbol as gpy_symbol. """
    	return self.database[self.ns[symbol]]

    def get(self,symbol):
    	""" retrieve symbol as pandas object. """
    	return self.database[self.ns[symbol]].vals

class gs_Energy:
    def __init__(self,index=[],kwargs_ns={}, kwargs_vals={}, **kwargs_oth):
        self.index = self.fixed_index()+index
        self.ns = self.index_ns(kwargs_ns=kwargs_ns)
        self.ns.update()
        self.database = DataBase.PM_database()

    @staticmethod
    def fixed_index():
        """ return indices that we cannot remove from the model without"""
        return ['h','i','p','f','b']

    def index_ns(self,kwargs_ns={}):
        """ define index namespace for global indices """
        return {** {k: df(k,kwargs_ns) for k in self.fixed_index()+self.index}, 
                ** {k: df(k,kwargs_ns) for k in self.time_sets() if 't' in self.index}}
    @staticmethod
    def time_sets():
        """ which time sets/subsets are used for years """
        return ['t','t0', 'tx0', 'tE', 'txE', 't0E', 'tx0E']
    @property
    def i2s(self):
        """ which indices are the plant set 'i' mapped to """
        return set(['m','g','p','f','v'])-set(self.index)

    def add_time_to_database(self,kwargs={}):
        if 't' in kwargs:
            self.database[self.ns['t']] = pd.Index(kwargs['t'],name=self.ns['t'])
        else:
            tbounds = (1,3) if 'tbounds' not in kwargs else kwargs['tbounds']
            self.database[self.ns['t']] = pd.Index(range(tbounds[0],tbounds[1]+1),name=self.ns['t'])

    def add_time_subsets_to_database(self):
        """ Add time subsets"""
        t_ints = self.get('t').astype(int).sort_values()
        self.database[self.ns['t0']] = t_ints[t_ints==t_ints[0]]
        self.database[self.ns['tE']] = t_ints[t_ints==t_ints[-1]]
        self.database[self.ns['tx0']] = t_ints[t_ints != t_ints[0]]
        self.database[self.ns['txE']] = t_ints[t_ints != t_ints[-1]]
        self.database[self.ns['t0E']] = self.get('t0').union(self.get('tE'))
        self.database[self.ns['tx0E']] = t_ints[~t_ints.isin(self.get('t0').union(self.get('tE')))]

    def g(self,symbol):
        """ retrieve symbol as gpy_symbol. """
        return self.database[self.ns[symbol]]

    def get(self,symbol):
        """ retrieve symbol as pandas object. """
        return self.database[self.ns[symbol]].vals

