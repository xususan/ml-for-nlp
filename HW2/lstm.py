import argparse
import torch
import torch.autograd as autograd
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchtext
from torchtext.vocab import Vectors, GloVe
import pickle
import pdb

EMBEDDING_SIZE = 128
NUM_LAYERS = 2
UNROLL = 35
BATCH_SIZE = 20

# Medium LSTM
HIDDEN = 650 # per layer
DROPOUT = 0.5
EPOCHS = 39
LR = 1 * 1.2 # decreased by 1.2 for each epoch after 6th
DECAY = 1.2
TEMP_EPOCH = 6
GRAD_NORM = 5

# Large LSTM
# HIDDEN = 1500 # per layer
# DROPOUT = 0.65
# EPOCHS = 55
# LR = 1 * 1.15 # decreased by 1.15 for each epoch after 14th
# DECAY = 1.15
# TEMP_EPOCH = 14
# GRAD_NORM = 10

# PARSE ARGS
# parser = argparse.ArgumentParser(description='LSTM Language Model')
# parser.add_argument('--mini', type=bool, default=False, help='run smaller dataset')
# args = parser.parse_args()


TEXT = torchtext.data.Field()
# Data distributed with the assignment
train, val, test = torchtext.datasets.LanguageModelingDataset.splits(
    path=".", 
    train="train.5k.txt", validation="valid.txt", test="valid.txt", text_field=TEXT)
TEXT.build_vocab(train)
if args.mini:
    TEXT.build_vocab(train, max_size=1000)
train_iter, val_iter, test_iter = torchtext.data.BPTTIterator.splits(
    (train, val, test), batch_size=BATCH_SIZE, device=-1, bptt_len=UNROLL, repeat=False)
url = 'https://s3-us-west-1.amazonaws.com/fasttext-vectors/wiki.simple.vec'
TEXT.vocab.load_vectors(vectors=Vectors('wiki.simple.vec', url=url))

VOCAB_SIZE = len(TEXT.vocab)

print("vocab size: " + str(VOCAB_SIZE))

class LSTM(nn.Module):
    def __init__(self, embedding_size, vocab_size, hidden_size, num_layers=2, dropout=DROPOUT):
        super(LSTM, self).__init__()
        self.embedding_size = embedding_size
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.embedding = nn.Embedding(vocab_size, embedding_size)
        self.rnn = nn.LSTM(embedding_size, hidden_size, num_layers, dropout=dropout)
        self.linear = nn.Linear(hidden_size, vocab_size)
        self.dropout = nn.Dropout(dropout)

    def forward(self, inputs, hidden):
        embedding = self.dropout(self.embedding(inputs)) # [bptt_len - 1 x batch x embedding_size]
        # embedding = embedding.transpose(0, 1)

        # hidden size: [layers x batch x units]
        output, hidden = self.rnn(embedding, hidden) # [bptt_len - 1 x batch x units]
        # embedding..view(1, batch_size, -1) without transpose
        output = self.dropout(output)
        output = self.linear(output) # [bptt_len - 1 x batch x vocab_size]
        # output.view(batch_size, -1)
        return output, hidden

rnn = LSTM(embedding_size=EMBEDDING_SIZE , vocab_size=VOCAB_SIZE, hidden_size=HIDDEN, num_layers=NUM_LAYERS, dropout=DROPOUT)
criterion = nn.CrossEntropyLoss()

# optimizer = optim.SGD(rnn.parameters(), lr=LR/DECAY)
optimizer = optim.Adadelta(rnn.parameters(), lr=LR/DECAY)
scheduler = optim.lr_scheduler.MultiStepLR(optimizer, milestones=[TEMP_EPOCH], gamma=1/DECAY)

def train_batch(model, criterion, optim, text, target, epoch):
    # initialize hidden vectors
    hidden = (Variable(torch.zeros(NUM_LAYERS, BATCH_SIZE, HIDDEN)),
            Variable(torch.zeros(NUM_LAYERS, BATCH_SIZE, HIDDEN))) # This includes (hidden, cell)

    if torch.cuda.is_available():
        hidden = (Variable(torch.zeros(NUM_LAYERS, BATCH_SIZE, HIDDEN)).cuda(),
            Variable(torch.zeros(NUM_LAYERS, BATCH_SIZE, HIDDEN)).cuda())

    # clear gradients
    model.zero_grad()
    # calculate forward pass
    output, hidden = model(text, hidden)
    # calculate loss
    output_flat = output.view(-1, VOCAB_SIZE)
    loss = criterion(output_flat, target) # output: [bptt_len-1 x batch x vocab_size]
    # target: [bptt_len-1 x batch]
    # backpropagate and step
    loss.backward()
    nn.utils.clip_grad_norm(model.parameters(), max_norm=GRAD_NORM)
    optimizer.step()
    return loss.data[0]

def train(model, criterion, optim):
    model.train()
    for epoch in range(EPOCHS):
    # for epoch in range(12):
        total_loss = 0
        counter = 0
        print(sum(1 for _ in train_iter))
        for batch in train_iter:
            text = batch.text[:-1,:]
            target = batch.text[1:,:].view(-1)

            if torch.cuda.is_available():
                text = text.cuda()
                target = target.cuda()

            batch_loss = train_batch(model, criterion, optim, text, target, epoch)
            total_loss += batch_loss
            # print(str(counter) + "   " + str(total_loss))
            counter += 1
        scheduler.step()
        print("learning rate: " + str(scheduler.get_lr()))
        print("Epoch " + str(epoch) + " Loss: " + str(total_loss))
        print(rnn)

def evaluate(model, val_iter, hidden=False):
    # correct = 0.0
    # total  = 0.0
    # num_zeros = 0.0
    total_loss = 0.0

    model.eval()

    # if hidden:
    h = (Variable(torch.zeros(NUM_LAYERS, BATCH_SIZE, HIDDEN)), 
        Variable(torch.zeros(NUM_LAYERS, BATCH_SIZE, HIDDEN)))

    for batch in val_iter:
        text = batch.text[:-1,:]
        target = batch.text[1:,:].view(-1)
        
        if torch.cuda.is_available():
            text = text.cuda()
            target = target.cuda()

        # if hidden:
        probs, h = model(text, h)
        probs_flat = probs.view(-1, VOCAB_SIZE)

        total_loss += criterion(probs_flat, target).data
        # else:
        #     probs = model(text)

        # _, preds = torch.max(probs, 1)
        # print(probs, target)
        # correct += sum(preds.view(-1, len(TEXT.vocab)) == target.data)
        # total += 1
        # num_zeros += sum(torch.zeros_like(target.data) == target.data)

    print(total_loss[0])
    return total_loss

####### CHECK FOR CUDA
if torch.cuda.is_available():
    print("USING CUDA")
    rnn = rnn.cuda()
#######

# train(rnn, criterion, optimizer)

filename = 'lstm_model.sav'
# pickle.dump(rnn, open(filename, 'wb'))

loaded_model = pickle.load(open(filename, 'rb'))
print("Validation Set")
evaluate(loaded_model, val_iter, hidden=True)
print("Test Set")
evaluate(loaded_model, test_iter, hidden=True)
