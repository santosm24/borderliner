import pandas
import logging
import sys

from borderliner.db.conn_abstract import DatabaseBackend
from borderliner.db.postgres_lib import PostgresBackend
from borderliner.db.redshift_lib import RedshiftBackend

# logging
logging.basicConfig(
    stream=sys.stdout, 
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s'
    )
logger = logging.getLogger()

class PipelineSource:
    def __init__(self,config:dict,*args,**kwargs) -> None:
        self.kwargs = kwargs
        self.pipeline_pid = self.kwargs.get('pipeline_pid',0)
        self.csv_chunks_files = []
        self.logger = logger
        self.config = config
        self._data:pandas.DataFrame|list = None
        self.chunk_size = -1
        self.metrics:dict = {
            'total_rows':0,
            'processed_rows':0
        }
    
    def extract(self):
        pass

    def __str__(self) -> str:
        return str(self.config)

    @property
    def data(self):
        source_empty = True
        if isinstance(self._data,list):
            if len(self._data) > 0:
                source_empty = False
        elif isinstance(self._data,pandas.DataFrame):
            source_empty = self._data.empty
        elif self._data == None:
            source_empty = True
        else:
            raise ValueError('Invalid data in SOURCE')
        if not source_empty:
            return self._data
            
        self.extract()
        
        return self._data
    
    

class PipelineSourceDatabase(PipelineSource):
    def __init__(self, config: dict,*args,**kwargs) -> None:
        super().__init__(config,*args,**kwargs)
        self.database_module = 'psycopg2'
        self.alchemy_engine_flag = 'psycopg2'
        self.driver_signature = ''
        self.backend:DatabaseBackend = None
        self.user:str = ''
        self.database:str = ''
        self.password:str = ''
        self.host:str = ''
        self.port:str = None
        self.queries = {}
        
        self.count = 0
        self.total_time = 0.0

        self.engine = None
        self.connection = None

        

        self.iteration_list = []
        self.deltas = {}
        self.primary_key = ()

        self.configure()
    
    def configure(self):
        self.user = self.config['username']
        self.password = self.config['password']
        self.host = self.config['host']
        self.port = self.config['port']
        match str(self.config['type']).upper():
            # TODO: dynamically import
            # i'll leave these dbs as native support.
            case 'POSTGRES':
                self.backend = PostgresBackend(
                    host=self.host,
                    database=self.config['database'],
                    user=self.user,
                    password=self.password,
                    port=self.port
                )
            case 'REDSHIFT':
                self.backend = RedshiftBackend(
                    host=self.host,
                    database=self.config['database'],
                    user=self.user,
                    password=self.password,
                    port=self.port
                )
            case 'IBMDB2':
                self.backend = RedshiftBackend(
                    host=self.host,
                    database=self.config['database'],
                    user=self.user,
                    password=self.password,
                    port=self.port
                )
        self.queries = self.config['queries']
        self.engine = self.backend.get_engine()
        self.connection = self.backend.get_connection()
    
    def populate_deltas(self):
        pass

    def populate_iteration_list(self):
        df = pandas.read_sql_query(
            self.queries['iterate'],
            self.engine
        )
        
        total_cols = int(df.shape[1])
        self._data = []
        for col in df.columns:
            df[col] = df[col].astype(str)
        
        df = df.to_dict(orient='records')
        slice_index = 1
        for item in df:
            self.logger.info(f'Extract by iteration: {item}')
            query = self.queries['extract'].format(
                **item
            )
            data = pandas.read_sql_query(query,self.engine)
            if self.kwargs.get('dump_data_csv',False):
                filename = f'slice_{str(slice_index).zfill(5)}_{self.pipeline_pid}.csv'                
                data.to_csv(
                    filename,
                    header=True,
                    index=False
                )
                self.csv_chunks_files.append(filename)
                self._data.append(data)
            else:
                self._data.append(data)
            slice_index += 1
        

    def extract_by_iteration(self):
        self.populate_iteration_list()

    def extract(self):
        if 'iterate' in self.queries:
            self.extract_by_iteration()
            return
        if self.chunk_size > 0: 
            data = pandas.read_sql_query(
                self.get_query('extract'),
                self.engine,
                chunksize=self.chunk_size)
            slice_index = 1
            for df in data:
                if self.kwargs.get('dump_data_csv',False):
                    filename = f'slice_{str(slice_index).zfill(5)}_{self.pipeline_pid}.csv'                
                    df.to_csv(
                        filename,
                        header=True,
                        index=False
                    )
                    self.csv_chunks_files.append(filename)
                    slice_index += 1
            self._data = data
        else:
            data = pandas.read_sql_query(
                self.get_query('extract'),
                self.engine)
            if self.kwargs.get('dump_data_csv',False):
                filename = f'slice_FULL_{self.pipeline_pid}.csv'                
                data.to_csv(
                    filename,
                    header=True,
                    index=False
                )
                self.csv_chunks_files.append(filename)
            self._data = data
            

    def get_query(self,query:str='extract'):
        print(self.queries)
        if query in self.queries:
            key_params = str(query)+'_params'
            if key_params in self.queries:
                return self.queries[query].format(
                    **self.queries[key_params]
                )
            else:
                return self.queries[query]
        
        
        raise Exception('Query not found.')




import requests
class PipelineSourceApi(PipelineSource):
    def __init__(self, config: dict, *args, **kwargs) -> None:
        super().__init__(config, *args, **kwargs)
        # TODO: Make sure they exists 
        self.auth_type = config['api'].get('auth', {}).get('type', None)
        self.client_id = config['api'].get('auth', {}).get('client_id', None)
        self.client_secret = config['api'].get('auth', {}).get('client_secret', None)
        self.access_token_url = config['api'].get('auth', {}).get('access_token_url', None)
        self.bearer = config['api'].get('auth', {}).get('bearer', None)
        self.auth_headers_extra = config['api'].get('auth', {}).get('auth_headers_extra', None)

        # request
        self.request_headers = config.get('api', {}).get('request', {}).get('headers')
        self.request_method = config.get('api', {}).get('request', {}).get('method')
        self.request_url = config.get('api', {}).get('request', {}).get('url')
        self.request_data = config.get('api', {}).get('request', {}).get('data')
        self.request_read_json_params = config.get('api', {}).get('request', {}).get('read_json_params')

    def get_access_token(self):
        if not self.access_token:
            data = {
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret
            }
            for key,value in self.auth_headers_extra:
                data[key] = value
            response = requests.post(self.access_token_url, data=data)
            response.raise_for_status()
            self.access_token = response.json()['access_token']
        return self.access_token

    def make_request_oauth2(self, url, method='GET', data=None, headers=None):
        headers = headers or {}        
        for key,value in self.request_headers.items():
            headers[key] = value
        if not 'Authorization' in headers:
            headers['Authorization'] = f'{self.bearer} {self.get_access_token()}'
        response = requests.request(method, url, headers=headers, data=data)
        response.raise_for_status()
        return response.json()

    def make_request_apikey(self, url, method='GET', data=None, headers=None):
        self.logger.info(f'requesting {url}')
        headers = headers or {}     
        if self.auth_headers_extra is not None:   
            for key,value in self.auth_headers_extra.items():
                headers[key] = value
        match str(self.auth_type).upper():
            case 'OAUTH2':
                if not 'Authorization' in headers:
                    headers['Authorization'] = f'{self.bearer} {self.get_access_token()}'
            # case 'APIKEY':
        if self.request_headers is not None:
            for key,value in self.request_headers.items():
                headers[key] = value
        response = requests.request(method, url, headers=headers, data=data)
        response.raise_for_status()
        return response.json()

    def make_request(self, url, method='GET', data=None, headers=None):
        self.logger.info(f'requesting {url}')
        headers = headers or {}     
        if self.auth_headers_extra is not None:   
            for key,value in self.auth_headers_extra.items():
                headers[key] = value
        match str(self.auth_type).upper():
            case 'OAUTH2':
                if not 'Authorization' in headers:
                    headers['Authorization'] = f'{self.bearer} {self.get_access_token()}'
            # case 'APIKEY':
        if self.request_headers is not None:
            for key,value in self.request_headers.items():
                headers[key] = value
        response = requests.request(method, url, headers=headers, data=data)
        if self.config.get('raise_for_status',False):
            response.raise_for_status()
        return response.json()

    def extract(self, *args, **kwargs):
        data_api = self.make_request(
                    url=self.request_url,
                    method=self.request_method,
                    data=self.request_data,            
                )
                
        # list or object?
        df = pandas.read_json(
            data_api,
            **self.request_read_json_params,
            )
        self._data = df

class PipelineSourceFlatFile(PipelineSource):
    pass
