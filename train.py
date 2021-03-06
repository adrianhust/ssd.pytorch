from __future__ import print_function
import torch
import torch.nn as nn
import torch.optim as optim
import torch.backends.cudnn as cudnn
import torchvision.transforms as transforms
import torch.nn.init as init
import argparse
from torch.autograd import Variable
import torch.utils.data as data
import sys
import os
from data import VOCroot, v2, v1, AnnotationTransform, VOCDetection, detection_collate, base_transform
from modules import MultiBoxLoss
from ssd import build_ssd
from timeit import default_timer as timer
import time


parser = argparse.ArgumentParser(description='Single Shot MultiBox Detector Training')
parser.add_argument('--version', default='v2', help='conv11_2(v2) or pool6(v1) as last layer')
parser.add_argument('--basenet', default='vgg16_reducedfc.pth', help='pretrained base model')
parser.add_argument('--jaccard_threshold', default=0.5, type=float, help='Min Jaccard index for matching')
parser.add_argument('--batch_size', default=32, type=int, help='Batch size for training')
parser.add_argument('--num_workers', default=4, type=int, help='Number of workers used in dataloading')
parser.add_argument('--iterations', default=120000, type=int, help='Number of training epochs')
parser.add_argument('--cuda', default=True, type=bool, help='Use cuda to train model')
parser.add_argument('--lr', '--learning-rate', default=1e-3, type=float, help='initial learning rate')
parser.add_argument('--momentum', default=0.9, type=float, help='momentum')
parser.add_argument('--weight_decay', default=5e-4, type=float, help='Weight decay for SGD')
parser.add_argument('--gamma', default=0.1, type=float, help='Gamma update for SGD')
parser.add_argument('--log_iters', default=True, type=bool, help='Print the loss at each iteration')
parser.add_argument('--save_folder', default='weights/', help='Location to save checkpoint models')
args = parser.parse_args()

cfg = (v1,v2)[args.version == 'v2']

if not os.path.exists(args.save_folder):
    os.mkdir(args.save_folder)

ssd_dim = 300 # only support 300 now
rgb_means = (104,117,123) # only support voc now
num_classes = 21
batch_size = args.batch_size
accum_batch_size = 32
iter_size = accum_batch_size / batch_size
max_iter = 120000
weight_decay = 0.0005
stepvalues = (80000, 100000, 120000)
gamma = 0.1
momentum = 0.9


net = build_ssd('train',300,21)
vgg_weights = torch.load(args.save_folder+args.basenet)
print('Loading base network...')
net.vgg.load_state_dict(vgg_weights)

if args.cuda:
    net.cuda()
    cudnn.benchmark = True


def xavier(param):
    init.xavier_uniform(param)


def weights_init(m):
     if isinstance(m, nn.Conv2d):
         xavier(m.weight.data)
         m.bias.data.zero_()

print('Initializing weights...')
# initialize newly added layers' weights with xavier method
net.extras.apply(weights_init)
net.loc.apply(weights_init)
net.conf.apply(weights_init)

optimizer = optim.SGD(net.parameters(), lr=args.lr, momentum=args.momentum, weight_decay=args.weight_decay)
criterion = MultiBoxLoss(num_classes,0.5,True,0,True,3,0.5,False)

def train():
    net.train()
    train_loss = 0
    print('Loading Dataset...')
    dataset = VOCDetection(VOCroot, 'train',base_transform(ssd_dim, rgb_means), AnnotationTransform())
    epoch_size = len(dataset) // args.batch_size
    print('Training SSD on',dataset.name)
    step_index = 0
    for iteration in range(max_iter):
        if iteration % epoch_size == 0:
            # create batch iterator
            batch_iterator = iter(data.DataLoader(dataset,batch_size, \
                                  shuffle=True,collate_fn=detection_collate))
            if iteration in stepvalues:
                step_index+=1
                adjust_learning_rate(optimizer, args.gamma, step_index)

        # load train data
        images, targets = next(batch_iterator)
        images = Variable(images.cuda())
        targets = [Variable(anno.cuda()) for anno in targets]
        #forward
        t0 = time.time()
        out = net(images)
        # backprop
        optimizer.zero_grad()
        loss = criterion(out, targets)
        loss.backward()
        optimizer.step()
        t1 = time.time()
        train_loss += loss.data[0]
        if iteration % 10 == 0:
            print('Timer: ',t1-t0)
            print('Loss: %f' % (loss.data[0]), end=' ')
        if iteration % 5000 == 0:
            torch.save(net.state_dict(),'weights/ssd_iter_new'+repr(iteration)+'.pth')
    torch.save(net,args.save_folder+''+args.version+'.pth')


def adjust_learning_rate(optimizer, gamma, step):
    """Sets the learning rate to the initial LR decayed by 10 at every specified step
    # Adapted from PyTorch Imagenet example:
    # https://github.com/pytorch/examples/blob/master/imagenet/main.py
    """
    lr = args.lr * (gamma ** (step))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


if __name__ == '__main__':
    train()
