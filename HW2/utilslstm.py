import argparse
import torch
import torch.autograd as autograd
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchtext
from torchtext.vocab import Vectors, GloVe
import math
import random
import pdb

torch.manual_seed(1)

def get_batch(batch, n=20):
    # n will be used later on to get smaller segments of text
    text = batch.text[:-1,:]
    target = batch.text[1:,:].view(-1)
    if torch.cuda.is_available():
        text = text.cuda()
        target = target.cuda()
    return text, target

def train_batch(model, text, target, criterion, optimizer, grad_norm):
    # initialize hidden vectors
    hidden = model.init_hidden() # This includes (hidden, cell)
    # clear gradients
    model.zero_grad()
    # calculate forward pass
    output, hidden = model(text, hidden)
    # calculate loss
    output_flat = output.view(-1, model.vocab_size)
    loss = criterion(output_flat, target) # output: [bptt_len-1 x batch x vocab_size]
    # target: [bptt_len-1 x batch]
    # backpropagate and step
    loss.backward()
    nn.utils.clip_grad_norm(model.parameters(), max_norm=grad_norm)
    optimizer.step()
    return loss.data[0]

def train(model, train_iter, num_epochs, criterion, optimizer, scheduler=None, grad_norm=5):
    model.train()
    filename = 'lstm_extension'
    for epoch in range(num_epochs):
        total_loss = 0
        for batch in train_iter:
            text, target = get_batch(batch)
            batch_loss = train_batch(model, text, target, criterion, optimizer, grad_norm)
            total_loss += batch_loss
            # if counter % 20 == 0:
                # print(str(counter) + "   " + str(total_loss))
            # counter += 1
        if scheduler:
            scheduler.step()
            print("learning rate: " + str(scheduler.get_lr()))
        print("Epoch " + str(epoch) + " Loss: " + str(total_loss))
        if epoch % 5 == 0:
            print("SAVING MODEL #" + str(epoch))
            torch.save(model.state_dict(), filename + str(epoch) + ".sav")

def evaluate(model, iter_data, criterion):
    model.eval()
    total_loss = 0.0
    total_len = 0.0
    h = model.init_hidden()
    for batch in iter_data:
        pdb.set_trace()
        text, target = get_batch(batch)
        pdb.set_trace()
        probs, h = model(text, h)
        pdb.set_trace()
        probs_flat = probs.view(-1, model.vocab_size)
        total_loss += len(text) * criterion(probs_flat, target).data
        total_len += len(text)
        # _, preds = torch.max(probs, 1)
        # print(probs, target)
        # correct += sum(preds.view(-1, len(TEXT.vocab)) == target.data)
        # total += 1
        # num_zeros += sum(torch.zeros_like(target.data) == target.data)
    print(total_loss[0] / total_len)
    return total_loss[0] / total_len
