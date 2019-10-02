# Mouse Movie Datasets
import torch
from mlutils.data.datasets import MovieSet
from mlutils.data.transforms import Subsequence, Subsample, Normalizer, ToTensor
from torch.utils.data.sampler import SubsetRandomSampler
from torch.utils.data import DataLoader


def load_movie_dataset(data_path, batch_size, stats_source='all', seq_len=30, area='V1', layer='L2/3', normalize=False,
                       tier='train'):
    field_names = ['inputs', 'behavior', 'eye_position', 'responses']

    # load the dataset
    dataset = MovieSet(data_path, *field_names)

    # configure the statistics source
    dataset.stats_source = stats_source

    transforms = []

    # configure the sequence length
    transforms.append(Subsequence(seq_len))

    # whether to add normalizer
    if normalize:
        transforms.append(Normalizer(dataset, ))

    transforms.append(ToTensor())

    # subselect to areas & layer
    areas = dataset.neurons.area
    layers = dataset.neurons.layer
    idx = np.where((areas == area) & (layers == layer))[0]

    # place the area & layer subsampler at the very beginning
    transforms.insert(-1, Subsample(idx))

    dataset.transforms = transforms


    idx = np.where(dataset.tiers == tier)[0]
    sampler = SubsetRandomSampler(idx)

    # create and return the data loader
    return DataLoader(dataset, sampler=sampler, batch_size=batch_size)







