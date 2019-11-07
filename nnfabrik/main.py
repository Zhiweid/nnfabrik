import datajoint as dj
import torch
import numpy as np
import os
import tempfile
import warnings

import utility
import datasets
import training
import models

from .utility.dj_helpers import make_hash, gitlog
from .utility.nnf_helper import split_module_name, dynamic_import

dj.config['database.host'] = 'datajoint-db.mlcloud.uni-tuebingen.de'
schema = dj.schema('nnfabrik_core')

dj.config['stores'] = {
    'minio': {    #  store in s3
        'protocol': 's3',
        'endpoint': 'cantor.mvl6.uni-tuebingen.de:9000',
        'bucket': 'nnfabrik',
        'location': 'dj-store',
        'access_key': os.environ['MINIO_ACCESS_KEY'],
        'secret_key': os.environ['MINIO_SECRET_KEY']
    }
}


@schema
class Fabrikant(dj.Manual):
    definition = """
    architect_name: varchar(32)       # Name of the contributor that added this entry
    ---
    email: varchar(64)      # e-mail address 
    affiliation: varchar(32) # conributor's affiliation
    """


@schema
class Model(dj.Manual):
    definition = """
    configurator: varchar(32)   # name of the configuration function
    config_hash: varchar(64)    # hash of the configuration object
    ---    
    config_object: longblob     # configuration object to be passed into the function
    -> Fabrikant.proj(model_architect='architect_name')
    model_comment= : varchar(64)  # short description
    model_ts=CURRENT_TIMESTAMP: timestamp    # UTZ timestamp at time of insertion

    """

    def add_entry(self, configurator, config_object, model_architect, model_comment=''):
        """
        configurator -- name of the function/class that's callable
        config_object -- actual Python object
        """

        try:
            callable(eval(configurator))
        except NameError:
            warnings.warn("configurator function does not exist. Table entry rejected")
            return

        config_hash = make_hash(config_object)
        key = dict(configurator=configurator, config_hash=config_hash, config_object=config_object,
                   model_architect=model_architect, model_comment=model_comment)
        self.insert1(key)

    def build_model(self, dataloader, seed, key=None):
        if key is None:
            key = {}

        configurator, config_object = (self & key).fetch1('configurator', 'config_object')
        if type(config_object).__name__ == 'recarray':
            config_object = {k: config_object[k][0].item() for k in config_object.dtype.fields}
        module_path, class_name = split_module_name(configurator)
        model_fn = dynamic_import(module_path, class_name) if module_path else eval('models.' + configurator)
        return model_fn(dataloader, seed, **config_object)


@schema
class Dataset(dj.Manual):
    definition = """
    dataset_loader: varchar(32)         # name of the dataset loader function
    dataset_config_hash: varchar(64)    # hash of the configuration object
    ---
    dataset_config: longblob     # dataset configuration object
    -> Fabrikant.proj(dataset_architect='architect_name')
    dataset_comment= : varchar(64)  # short description
    dataset_ts=CURRENT_TIMESTAMP: timestamp    # UTZ timestamp at time of insertion
    """

    def add_entry(self, dataset_loader, dataset_config, dataset_architect, dataset_comment=''):
        """
        inserts one new entry into the Dataset Table
        dataset_loader -- name of dataset function/class that's callable
        dataset_config -- actual Python object with which the dataset function is called
        """

        try:
            callable(eval(dataset_loader))
        except NameError:
            warnings.warn("dataset_loader function does not exist. Table entry rejected")
            return

        dataset_config_hash = make_hash(dataset_config)
        key = dict(dataset_loader=dataset_loader, dataset_config_hash=dataset_config_hash,
                   dataset_config=dataset_config, dataset_architect=dataset_architect, dataset_comment=dataset_comment)
        self.insert1(key)

    def get_dataloader(self, seed, key=None):
        """
        Returns a dataloader for a given dataset loader function and its corresponding configurations
        dataloader: is expected to be a dict in the form of
                            {
                            'train_loader': torch.utils.data.DataLoader,
                             'val_loader': torch.utils.data.DataLoader,
                             'test_loader: torch.utils.data.DataLoader,
                             }
                             or a similar iterable object
                each loader should have as first argument the input such that
                    next(iter(train_loader)): [input, responses, ...]
                the input should have the following form:
                    [batch_size, channels, px_x, px_y, ...]
        """
        if key is None:
            key = {}

        dataset_loader, dataset_config = (self & key).fetch1('dataset_loader', 'dataset_config')
        if type(dataset_config).__name__ == 'recarray':
            dataset_config = {k: dataset_config[k][0].item() for k in dataset_config.dtype.fields}
        module_path, class_name = split_module_name(dataset_loader)
        dataset_fn = dynamic_import(module_path, class_name) if module_path else eval('datasets.' + dataset_loader)
        return dataset_fn(seed=seed, **dataset_config)


@schema
class Trainer(dj.Manual):
    definition = """
    training_function: varchar(32)     # name of the Trainer loader function
    training_config_hash: varchar(64)  # hash of the configuration object
    ---
    training_config: longblob          # training configuration object
    -> Fabrikant.proj(trainer_architect='architect_name')
    trainer_comment= : varchar(64)  # short description
    trainer_ts=CURRENT_TIMESTAMP: timestamp    # UTZ timestamp at time of insertion
    """

    def add_entry(self, training_function, training_config, trainer_architect, trainer_comment=''):
        """
        inserts one new entry into the Trainer Table
        training_function -- name of trainer function/class that's callable
        training_config -- actual Python object with which the trainer function is called
        """

        try:
            callable(eval(training_function))
        except NameError:
            warnings.warn("dataset_loader function does not exist. Table entry rejected")
            return

        training_config_hash = make_hash(training_config)
        key = dict(training_function=training_function, training_config_hash=training_config_hash,
                   training_config=training_config, trainer_architect=trainer_architect,
                   trainer_comment=trainer_comment)
        self.insert1(key)

    def get_trainer(self, key=None):
        """
        Returns the training function for a given training function and its corresponding configurations
        """
        if key is None:
            key = {}

        training_function, training_config = (self & key).fetch1('training_function', 'training_config')
        if type(training_config).__name__ == 'recarray':
            training_config = {k: training_config[k][0].item() for k in training_config.dtype.fields}
        module_path, class_name = split_module_name(training_function)
        trainer_fn = dynamic_import(module_path, class_name) if module_path else eval('training.' + training_function)
        return trainer_fn, training_config


@schema
class Seed(dj.Manual):
    definition = """
    seed:   int     # Random seed that is passed to the model- and dataset-builder
    """


@schema
class TrainedModel(dj.Computed):
    definition = """
    -> Model
    -> Dataset
    -> Trainer
    -> Seed
    ---
    score:   float  # loss
    output: longblob  # trainer object's output
    ->Fabrikant
    trainedmodel_ts=CURRENT_TIMESTAMP: timestamp    # UTZ timestamp at time of insertion
    """

    class ModelStorage(dj.Part):
        definition = """
        # Contains the paths to the stored models

        -> master
        ---
        model_state:            attach@minio   
        """

    def make(self, key):
        architect_name = (Fabrikant & key).fetch1('architect_name')
        seed = (Seed & key).fetch1('seed')
        trainer, trainer_config = (Trainer & key).get_trainer()
        dataloader = (Dataset & key).get_dataloader(seed)

        # passes the input dimensions to the model builder function
        model = (Model & key).build_model(dataloader, seed)

        # model training
        score, output, model_state = trainer(model, seed, **trainer_config, **dataloader)
        with tempfile.TemporaryDirectory() as trained_models:
            filename = make_hash(key) + '.pth.tar'
            filepath = os.path.join(trained_models, filename)
            torch.save(model_state, filepath)

            key['score'] = score
            key['output'] = output
            key['architect_name'] = architect_name
            self.insert1(key)

            key['model_state'] = filepath
            self.ModelStorage.insert1(key, ignore_extra_fields=True)