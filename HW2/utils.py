import numpy as np
import torchtext 
import torch
import torch.autograd as autograd


def validate(model, val_iter):
	correct = 0.0
	total  = 0.0
	last_pred = None
	for batch in val_iter:
		# Take every row except bottom row = last word in each obs.
		x = batch.text[:-1,:]
		y = batch.text[-1, :].squeeze()
		probs = model(x)
		_, preds = torch.max(probs, 1)

		correct += sum(preds == y.data)
		total += batch.text.size()[1] - 1
		print(preds, y)
	print(correct,total)
	return correct / total

def train(model, train_iter, num_epochs, criterion, optimizer):

	for epoch in range(num_epochs):
		for batch in train_iter:
			last_pred = None
			for x in batch.text.t():
				model.zero_grad()
				xs = (batch.text.t())
				probs = model.forward(xs)

				# cut off the last prediction for now, use it later
				current_probs = probs[:-1] # Check the size of this
				current_probs = torch.cat([last_pred, current_probs]) if last_pred is not None else current_probs


				# Cut off the first target unless there is a previous prediction
				ys = xs[0, :] if last_pred is not None else xs[0, 1:]
				targets= ys
				loss = criterion(probs, target)
				loss.backward()
				optimizer.step()
