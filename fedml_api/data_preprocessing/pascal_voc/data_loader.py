import logging

import torch.utils.data as data
import numpy as np

from torchvision import transforms
import fedml_api.data_preprocessing.pascal_voc.transforms as custom_transforms
from fedml_api.data_preprocessing.pascal_voc.datasets import PascalVocDataset

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _data_transforms_pascal_voc():
    PASCAL_VOC_MEAN = (0.485, 0.456, 0.406)
    PASCAL_VOC_STD = (0.229, 0.224, 0.225)

    train_transform = transforms.Compose([
        custom_transforms.RandomMirror(),
        custom_transforms.RandomScaleCrop(513, 513),
        custom_transforms.RandomGaussianBlur(),
        custom_transforms.ToTensor(),
        custom_transforms.Normalize([.485, .456, .406], [.229, .224, .225]),
    ])

    val_transform = transforms.Compose([
        custom_transforms.FixedScaleCrop(513),
        custom_transforms.Normalize(mean=PASCAL_VOC_MEAN, std=PASCAL_VOC_STD),
        custom_transforms.ToTensor()
    ])

    return train_transform, val_transform


# for centralized training
def get_dataloader(dataset, datadir, train_bs, test_bs, dataidxs=None):
    return get_dataloader_pascal_voc(datadir, train_bs, test_bs, dataidxs)


# for local devices
def get_dataloader_test(datadir, train_bs, test_bs, dataidxs_train, dataidxs_test):
    return get_dataloader_pascal_voc_test(datadir, train_bs, test_bs, dataidxs_train, dataidxs_test)


def get_dataloader_pascal_voc(datadir, train_bs, test_bs, dataidxs=None):
    transform_train, transform_test = _data_transforms_pascal_voc()

    train_ds = PascalVocDataset(datadir,
                                split='train',
                                transform=transform_train,
                                dataidxs=dataidxs)

    test_ds = PascalVocDataset(datadir,
                               split='val',
                               transform=transform_test)

    train_dl = data.DataLoader(dataset=train_ds, batch_size=train_bs, shuffle=True, drop_last=True)
    test_dl = data.DataLoader(dataset=test_ds, batch_size=test_bs, shuffle=False, drop_last=True)

    return train_dl, test_dl, len(train_ds.classes)


def get_dataloader_pascal_voc_test(datadir, train_bs, test_bs, dataidxs_train=None, dataidxs_test=None):
    transform_train, transform_test = _data_transforms_pascal_voc()

    train_ds = PascalVocDataset(datadir,
                                split='train',
                                transform=transform_train,
                                dataidxs=dataidxs_train)

    test_ds = PascalVocDataset(datadir,
                               split='val',
                               transform=transform_test,
                               dataidxs=dataidxs_test)

    train_dl = data.DataLoader(dataset=train_ds, batch_size=train_bs, shuffle=True, drop_last=True)
    test_dl = data.DataLoader(dataset=test_ds, batch_size=test_bs, shuffle=False, drop_last=True)

    return train_dl, test_dl, len(train_ds.classes)


def record_net_data_stats(y_train, net_dataidx_map):
    net_cls_counts = {}

    for net_i, dataidx in net_dataidx_map.items():
        unq, unq_cnt = np.unique(y_train[dataidx], return_counts=True)
        tmp = {unq[i]: unq_cnt[i] for i in range(len(unq))}
        net_cls_counts[net_i] = tmp
    logging.debug('Data statistics: %s' % str(net_cls_counts))
    return net_cls_counts


def load_pascal_voc_data(datadir):
    transform_train, transform_test = _data_transforms_pascal_voc()

    train_ds = PascalVocDataset(datadir, split='train', transform=transform_train)
    test_ds = PascalVocDataset(datadir, split='val', transform=transform_test)

    return train_ds.images, train_ds.targets, train_ds.classes, test_ds.images, test_ds.targets, test_ds.classes


# Get a partition map for each client
def partition_data(datadir, partition, n_nets, alpha):
    traindata_cls_counts = None
    net_dataidx_map = None
    logging.info("*********partition data***************")
    train_images, train_targets, train_categories, _, __, ___ = load_pascal_voc_data(datadir)
    n_train = len(train_images)  # Number of training samples

    if partition == "homo":
        total_num = n_train
        idxs = np.random.permutation(total_num)
        batch_idxs = np.array_split(idxs, n_nets)  # As many splits as n_nets = number of clients
        net_dataidx_map = {i: batch_idxs[i] for i in range(n_nets)}

    # non-iid data distribution
    # TODO: Add custom non-iid distribution option - hetero-fix
    elif partition == "hetero":
        min_size = 0
        # K = train_dataset.num_classes
        categories = train_categories
        N = n_train  # Number of labels/training samples
        logging.info("N = " + str(N))
        net_dataidx_map = {}

        while min_size < 10:
            idx_batch = [[] for _1 in range(n_nets)]  # Create a list of empty lists for clients
            # for each class in the dataset
            # one image may have multiple categories.
            for c in range(len(categories)):
                if c > 0:
                    idx_k = np.asarray([np.any(train_targets[i] == c) and not np.any(
                        train_targets[i][train_targets[i] < c]) for i in
                                        range(len(train_targets))])

                else:
                    idx_k = np.asarray(
                        [np.any(train_targets[i] == c) for i in range(len(train_targets))])

                idx_k = np.where(idx_k)[0]  # Get the indices of images that have category = c
                np.random.shuffle(idx_k)  # Shuffle these indices

                # alpha, parameter for Dirichlet dist, vector containing positive concentration parameters (larger
                # the value more even the distribution)

                # eg. np.random.dirichlet([10, 20, 30]) -> array([0.12926711, 0.37333834, 0.49739455])
                proportions = np.random.dirichlet(np.repeat(alpha, n_nets))

                # Balance
                # If client's index list is smaller than num_labels/num_clients, keep sample value for the
                # client as it is, else change it to 0.
                proportions = np.array([p * (len(idx_j) < N / n_nets) for p, idx_j in zip(proportions, idx_batch)])

                # Normalize across all samples
                proportions = proportions / proportions.sum()

                # eg. For 10 clients, 15 samples -> [0,0,2,2,2,2,14,14,14] -> 9 elements
                proportions = (np.cumsum(proportions) * len(idx_k)).astype(int)[:-1]

                # Split sample indices based on proportions
                # eg. Split [1,2,3,4,5,6,7,8,9,0,12,14,15,16,13] based on index values in proportions
                # eg. np.split(np.asarray([1,2,3,4,5,6,7,8,9,0,12,14,15,16,13]), [0,0,2,2,2,2,14,14,14])
                # -> [array([], dtype=int64),
                #  array([], dtype=int64),
                #  array([1, 2]),
                #  array([], dtype=int64),
                #  array([], dtype=int64),
                #  array([], dtype=int64),
                #  array([ 3,  4,  5,  6,  7,  8,  9,  0, 12, 14, 15, 16]),
                #  array([], dtype=int64),
                #  array([], dtype=int64),
                #  array([13])]
                idx_batch = [idx_j + idx.tolist() for idx_j, idx in zip(idx_batch, np.split(idx_k, proportions))]

                min_size = min([len(idx_j) for idx_j in idx_batch])

        for j in range(n_nets):
            np.random.shuffle(idx_batch[j])
            net_dataidx_map[j] = idx_batch[j]

        traindata_cls_counts = None  # record_net_data_stats(y_train, net_dataidx_map)

        # print("Final partition for clients: ")
        # for key in net_dataidx_map:
        #     print('Client: ', key)
        #     print('Number of samples: ', len(net_dataidx_map[key]))

    return net_dataidx_map, traindata_cls_counts


def load_partition_data_distributed_pascal_voc(process_id, dataset, data_dir, partition_method, partition_alpha,
                                               client_number, batch_size):
    net_dataidx_map, traindata_cls_counts = partition_data(data_dir,
                                                           partition_method,
                                                           client_number,
                                                           partition_alpha)
    logging.info("traindata_cls_counts = " + str(traindata_cls_counts))
    train_data_num = sum([len(net_dataidx_map[r]) for r in range(client_number)])

    # get global test data
    if process_id == 0:
        train_data_global, test_data_global, class_num = get_dataloader(dataset, data_dir, batch_size, batch_size)
        logging.info("train_dl_global number = " + str(len(train_data_global)))
        logging.info("test_dl_global number = " + str(len(test_data_global)))
        train_data_local_dict = None
        test_data_local_dict = None
        data_local_num_dict = None
    else:
        # get local dataset
        client_id = process_id - 1
        dataidxs = net_dataidx_map[client_id]
        # print(dataidxs)
        local_data_num = len(dataidxs)
        logging.info("rank = %d, number of local samples = %d" % (process_id, local_data_num))
        # training batch size = 64; algorithms batch size = 32
        train_data_local, test_data_local, class_num = get_dataloader(dataset, data_dir, batch_size, batch_size,
                                                                      dataidxs)
        logging.info("process_id = %d, batch_num_train_local = %d, batch_num_test_local = %d" % (
            process_id, len(train_data_local), len(test_data_local)))

        data_local_num_dict = {client_id: local_data_num}
        train_data_local_dict = {client_id: train_data_local}
        test_data_local_dict = {client_id: test_data_local}
        train_data_global = None
        test_data_global = None
    return train_data_num, train_data_global, test_data_global, data_local_num_dict, train_data_local_dict, \
           test_data_local_dict, class_num


# Called from main_fedseg
def load_partition_data_pascal_voc(dataset, data_dir, partition_method, partition_alpha, client_number, batch_size):
    net_dataidx_map, traindata_cls_counts = partition_data(data_dir,
                                                           partition_method,
                                                           client_number,
                                                           partition_alpha)

    logging.info("traindata_cls_counts = " + str(traindata_cls_counts))
    train_data_num = sum([len(net_dataidx_map[r]) for r in range(client_number)])

    # Global train and test data
    train_data_global, test_data_global, class_num = get_dataloader(dataset, data_dir, batch_size, batch_size)
    logging.info("train_dl_global number = " + str(len(train_data_global)))
    logging.info("test_dl_global number = " + str(len(test_data_global)))
    test_data_num = len(test_data_global)

    # get local dataset
    data_local_num_dict = dict()  # Number of samples for each client
    train_data_local_dict = dict()
    test_data_local_dict = dict()

    for client_idx in range(client_number):
        dataidxs = net_dataidx_map[client_idx]  # get dataId list for client generated using Dirichlet sampling
        local_data_num = len(dataidxs)  # How many samples does client have?
        data_local_num_dict[client_idx] = local_data_num
        logging.info("client_idx = %d, number of local samples = %d" % (client_idx, local_data_num))

        # training batch size = 64; algorithms batch size = 32
        train_data_local, test_data_local, class_num = get_dataloader(dataset, data_dir, batch_size, batch_size,
                                                                      dataidxs)
        logging.info("client_idx = %d, batch_num_train_local = %d, batch_num_test_local = %d" % (
            client_idx, len(train_data_local), len(test_data_local)))

        # Store dataloaders for each client as they contain specific data
        train_data_local_dict[client_idx] = train_data_local
        test_data_local_dict[client_idx] = test_data_local
    return train_data_num, test_data_num, train_data_global, test_data_global, data_local_num_dict, \
           train_data_local_dict, test_data_local_dict, class_num