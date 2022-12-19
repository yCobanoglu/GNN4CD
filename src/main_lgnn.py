import numpy as np
import os
from data_generator import Generator
from load import get_lg_inputs
from models import lGNN_multiclass
import time

import argparse

import torch
import torch.nn as nn
from torch import optim
from losses import compute_loss_multiclass, compute_accuracy_multiclass

parser = argparse.ArgumentParser()

###############################################################################
#                             General Settings                                #
###############################################################################
parser.add_argument('--num_examples_train', nargs='?', const=1, type=int,
                    default=int(6000))
parser.add_argument('--num_examples_test', nargs='?', const=1, type=int,
                    default=int(1000))
parser.add_argument('--edge_density', nargs='?', const=1, type=float,
                    default=0.2)
parser.add_argument('--p_SBM', nargs='?', const=1, type=float,
                    default=0.0)
parser.add_argument('--q_SBM', nargs='?', const=1, type=float,
                    default=0.045)
parser.add_argument('--random_noise', action='store_true')
parser.add_argument('--noise', nargs='?', const=1, type=float, default=0.03)
parser.add_argument('--noise_model', nargs='?', const=1, type=int, default=2)
parser.add_argument('--generative_model', nargs='?', const=1, type=str,
                    default='SBM_multiclass')
parser.add_argument('--batch_size', nargs='?', const=1, type=int, default=1)
parser.add_argument('--mode', nargs='?', const=1, type=str, default='train')
parser.add_argument('--path_dataset', nargs='?', const=1, type=str, default='')
parser.add_argument('--path_gnn', nargs='?', const=1, type=str, default='')
parser.add_argument('--filename_existing_gnn', nargs='?', const=1, type=str, default='')
parser.add_argument('--print_freq', nargs='?', const=1, type=int, default=100)
parser.add_argument('--test_freq', nargs='?', const=1, type=int, default=500)
parser.add_argument('--save_freq', nargs='?', const=1, type=int, default=2000)
parser.add_argument('--clip_grad_norm', nargs='?', const=1, type=float,
                    default=40.0)
parser.add_argument('--freeze_bn', dest='eval_vs_train', action='store_true')
parser.set_defaults(eval_vs_train=False)

###############################################################################
#                                 GNN Settings                                #
###############################################################################

parser.add_argument('--num_features', nargs='?', const=1, type=int,
                    default=8)
parser.add_argument('--num_layers', nargs='?', const=1, type=int,
                    default=30)
parser.add_argument('--n_classes', nargs='?', const=1, type=int,
                    default=5)
parser.add_argument('--J', nargs='?', const=1, type=int, default=2)
parser.add_argument('--N_train', nargs='?', const=1, type=int, default=100)
parser.add_argument('--N_test', nargs='?', const=1, type=int, default=100)
parser.add_argument('--lr', nargs='?', const=1, type=float, default=4e-3)

args = parser.parse_args()

if torch.cuda.is_available():
    dtype = torch.cuda.FloatTensor
    dtype_l = torch.cuda.LongTensor
    torch.cuda.manual_seed(42)
else:
    dtype = torch.FloatTensor
    dtype_l = torch.LongTensor
    torch.manual_seed(42)

batch_size = args.batch_size
criterion = nn.CrossEntropyLoss()
# template1 = '{:<10} {:<10} {:<10} {:<15} {:<10} {:<10} {:<10} '
# template2 = '{:<10} {:<10.5f} {:<10.5f} {:<15} {:<10} {:<10} {:<10.3f} \n'
template1 = '{:<10} {:<10} {:<10} {:<10} {:<10} '
template2 = '{:<10} {:<10.5f} {:<10.5f} {:<10} {:<10.3f} \n'
template3 = '{:<10} {:<10} {:<10} '
template4 = '{:<10} {:<10.5f} {:<10.5f} \n'

def train_single(gnn, optimizer, gen, n_classes, it):
    start = time.time()
    W, labels = gen.sample_otf_single(is_training=True, cuda=torch.cuda.is_available())
    labels = labels.type(dtype_l)

    print ('Num of edges: ', np.sum(W))

    if (args.generative_model == 'SBM_multiclass') and (args.n_classes == 2):
        labels = (labels + 1)/2

    WW, x, WW_lg, y, P = get_lg_inputs(W, args.J)

    if (torch.cuda.is_available()):
        WW.cuda()
        x.cuda()
        WW_lg.cuda()
        y.cuda()
        P.cuda()

    pred = gnn(WW.type(dtype), x.type(dtype), WW_lg.type(dtype), y.type(dtype), P.type(dtype))

    loss = compute_loss_multiclass(pred, labels, n_classes)
    gnn.zero_grad()
    loss.backward()
    nn.utils.clip_grad_norm_(gnn.parameters(), args.clip_grad_norm)
    optimizer.step()

    acc = compute_accuracy_multiclass(pred, labels, n_classes)

    elapsed = time.time() - start

    if(torch.cuda.is_available()):
        loss_value = float(loss.data.cpu().numpy())
    else:
        loss_value = float(loss.data.numpy())

    info = ['iter', 'avg loss', 'avg acc', 'edge_density',
            'noise', 'model', 'elapsed']
    out = [it, loss_value, acc, args.edge_density,
           args.noise, 'LGNN', elapsed]
    print(template1.format(*info))
    print(template2.format(*out))

    del WW
    del WW_lg
    del x
    del y
    del P

    return loss_value, acc

def train(gnn, gen, n_classes=args.n_classes, iters=args.num_examples_train):
    gnn.train()
    optimizer = torch.optim.Adamax(gnn.parameters(), lr=args.lr)
    loss_lst = np.zeros([iters])
    acc_lst = np.zeros([iters])
    for it in range(iters):

        loss_single, acc_single = train_single(gnn, optimizer, gen, n_classes, it)
        loss_lst[it] = loss_single
        acc_lst[it] = acc_single
        torch.cuda.empty_cache()

        if (it % 100 == 0) and (it >= 100):
            print ('Check_pt at iteration ' + str(it) + ' :')
            print ('Avg train loss', np.mean(loss_lst[it-100:it]))
            print ('Avg train acc', np.mean(acc_lst[it-100:it]))
            print ('Std train acc', np.std(acc_lst[it-100:it]))

    print ('Final avg train loss', np.mean(loss_lst))
    print ('Final avg train acc', np.mean(acc_lst))
    print ('Final std train acc', np.std(acc_lst))

def eval_single(gnn, gen, n_classes, it):

    start = time.time()
    W, labels = gen.sample_otf_single(is_training=False, cuda=torch.cuda.is_available())
    labels = labels.type(dtype_l)
    if (args.generative_model == 'SBM_multiclass') and (args.n_classes == 2):
        labels = (labels + 1)/2
    WW, x, WW_lg, y, P = get_lg_inputs(W, args.J)

    if (torch.cuda.is_available()):
        WW.cuda()
        x.cuda()
        WW_lg.cuda()
        y.cuda()
        P.cuda()

    pred_single = gnn(WW.type(dtype), x.type(dtype), WW_lg.type(dtype), y.type(dtype), P.type(dtype))
    labels_single = labels

    loss_test = compute_loss_multiclass(pred_single, labels_single, n_classes)
    acc_test = compute_accuracy_multiclass(pred_single, labels_single, n_classes)

    elapsed = time.time() - start

    if(torch.cuda.is_available()):
        loss_value = float(loss_test.data.cpu().numpy())
    else:
        loss_value = float(loss_test.data.numpy())

    info = ['iter', 'avg loss', 'avg acc', 'edge_density',
            'noise', 'model', 'elapsed']
    out = [it, loss_value, acc_test, args.edge_density,
           args.noise, 'LGNN', elapsed]
    print(template1.format(*info))
    print(template2.format(*out))

    del WW
    del WW_lg
    del x
    del y
    del P

    return loss_value, acc_test

def eval(gnn, gen, n_classes, iters=args.num_examples_test):
    gnn.train()
    loss_lst = np.zeros([iters])
    acc_lst = np.zeros([iters])
    for it in range(iters):
        loss_single, acc_single = eval_single(gnn, gen, n_classes, it)
        loss_lst[it] = loss_single
        acc_lst[it] = acc_single
        torch.cuda.empty_cache()
    print ('Testing results:')
    print ('Avg test loss', np.mean(loss_lst))
    print ('Avg test acc', np.mean(acc_lst))
    print ('Std test acc', np.std(acc_lst))



if __name__ == '__main__':

    print ('main file starts here')

    gen = Generator()
    gen.N_train = args.N_train
    gen.N_test = args.N_test
    gen.edge_density = args.edge_density
    gen.p_SBM = args.p_SBM
    gen.q_SBM = args.q_SBM
    gen.random_noise = args.random_noise
    gen.noise = args.noise
    gen.noise_model = args.noise_model
    gen.generative_model = args.generative_model
    gen.n_classes = args.n_classes

    torch.backends.cudnn.enabled=False

    if (args.mode == 'test'):
        print ('In testing mode')
        filename = args.filename_existing_gnn
        path_plus_name = os.path.join(args.path_gnn, filename)
        if ((filename != '') and (os.path.exists(path_plus_name))):
            print ('Loading gnn ' + filename)
            gnn = torch.load(path_plus_name)
            if torch.cuda.is_available():
                gnn.cuda()
        else:
            print ('No such a gnn exists; creating a brand new one')
            if (args.generative_model == 'SBM_multiclass'):
                gnn = lGNN_multiclass(args.num_features, args.num_layers, args.J + 2, n_classes=args.n_classes)
            filename = 'lgnn_J' + str(args.J) + '_lyr' + str(args.num_layers) + '_Ntr' + str(args.N_train) + '_num' + str(args.num_examples_train)
            path_plus_name = os.path.join(args.path_gnn, filename)
            if torch.cuda.is_available():
                gnn.cuda()
            print ('Training begins')


    elif (args.mode == 'train'):
        filename = args.filename_existing_gnn
        path_plus_name = os.path.join(args.path_gnn, filename)
        if ((filename != '') and (os.path.exists(path_plus_name))):
            print ('Loading gnn ' + filename)
            gnn = torch.load(path_plus_name)
            filename = filename + '_Ntr' + str(args.N_train) + '_num' + str(args.num_examples_train)
            path_plus_name = os.path.join(args.path_gnn, filename)
        else:
            print ('No such a gnn exists; creating a brand new one')
            filename = 'lgnn_J' + str(args.J) + '_lyr' + str(args.num_layers) + '_Ntr' + str(args.N_train) + '_num' + str(args.num_examples_train)
            path_plus_name = os.path.join(args.path_gnn, filename)
            if (args.generative_model == 'SBM_multiclass'):
                gnn = lGNN_multiclass(args.num_features, args.num_layers, args.J + 2, n_classes=args.n_classes)

        if torch.cuda.is_available():
            gnn.cuda()
        print ('Training begins')
        if (args.generative_model == 'SBM'):
            train(gnn, gen, 2)
        elif (args.generative_model == 'SBM_multiclass'):
            train(gnn, gen, args.n_classes)
        print ('Saving gnn ' + filename)
        if torch.cuda.is_available():
            torch.save(gnn.cpu(), path_plus_name)
            gnn.cuda()
        else:
            torch.save(gnn, path_plus_name)

    print ('Testing the GNN:')
    if args.eval_vs_train:
        print ('model status: eval')
        gnn.eval()
    else:
        print ('model status: train')
        gnn.train()

    eval(gnn, gen, args.n_classes)
