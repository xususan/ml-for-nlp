import numpy as np
import torch
import torch.autograd as autograd
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import pdb

N_PROP_TYPES = 8
N_PROP_OBJECTS = 35

def logsumexp(inputs, dim=None, keepdim=False):
    return (inputs - F.log_softmax(inputs)).mean(dim, keepdim=keepdim)

class Listener0Model(nn.Module):
    def __init__(self, vocab_sz, num_scenes, hidden_sz, output_sz, dropout): #figure out what parameters later
        super(Listener0Model, self).__init__()
        self.vocab_sz = vocab_sz
        self.num_scenes = num_scenes
        self.hidden_sz = hidden_sz
        self.output_sz = output_sz
        self.dropout_p = dropout # need to pass this in somewhere

        self.scene_input_sz = N_PROP_TYPES * N_PROP_OBJECTS

        self.scene_encoder = LinearSceneEncoder("Listener0", self.scene_input_sz, hidden_sz, dropout) #figure out what parameters later
        self.string_encoder = LinearStringEncoder("Listener0", vocab_sz, hidden_sz, dropout) #figure out what parameters later
        self.scorer = MLPScorer("Listener0", hidden_sz, output_sz, dropout) #figure out what parameters later
        # self.fc = nn.Linear() #Insert something here what is this?


    def forward(self, data, alt_data): # alt_data seems to be a list, data seems to have both string and image
        pdb.set_trace()
        scene_enc = self.scene_encoder(data)
        alt_scene_enc = [self.scene_encoder(alt) for alt in alt_data]
        string_enc = self.string_encoder(data) # data has the string?

        scenes = [scene_enc] + alt_scene_enc # List of length 2
        labels = np.zeros((len(data),)) # length 100
        log_probs = self.scorer(string_enc, scenes, labels)

        return log_probs

class Speaker0Model(nn.Module):
    def __init__(self, vocab_sz, hidden_sz, dropout): #figure out what parameters later
        super(Speaker0Model, self).__init__()

        self.vocab_sz = vocab_sz
        self.hidden_sz = hidden_sz
        self.scene_input_sz = N_PROP_OBJECTS * N_PROP_TYPES

        self.scene_encoder = LinearSceneEncoder("Speaker0SceneEncoder", self.scene_input_sz, hidden_sz, dropout)
        self.string_decoder = MLPStringDecoder("Speaker0StringDecoder", self.hidden_sz, self.hidden_sz, self.vocab_sz, dropout) # Not sure what the input and hidden size are for this
        # self.fc = nn.Linear() #Insert something here Why is this needed?

        self.dropout_p = dropout

    def forward(self, data, alt_data):
        scene_enc = self.scene_encoder(data)
        losses = self.string_decoder(scene_enc, data) # this seems off. no calling alt_data? <- this is right bc speaker0 is naive

        return losses, np.asarray(0)

    # I have no idea what's going on here
    # def sample(self, data, alt_data, viterbi, quantile=None):
    def sample(self, data, alt_data):
        scene_enc = self.scene_encoder(data)
        probs, sample = self.string_decoder(scene_enc)
        return probs, np.zeros(probs.shape), sample

class SamplingSpeaker1Model(nn.Module):
    def __init__(self, vocab_sz, num_scenes, hidden_sz, output_sz, dropout): #figure out what parameters later
        super(SamplingSpeaker1Model, self).__init__()

        self.listener0 = Listener0Model(vocab_sz, num_scenes, hidden_sz, output_sz, dropout)
        self.speaker0 = Speaker0Model(vocab_sz, hidden_sz, dropout)

        # self.fc = nn.Linear() # figure out parameters

    def sample(self, data, alt_data, viterbi, quantile=None):
        if viterbi or quantile is not None:
            n_samples = 10
        else:
            n_samples = 1

        speaker_scores = np.zeros((len(data), n_samples))
        listener_scores = np.zeros((len(data), n_samples))

        all_fake_scenes = []
        for i_sample in range(n_samples):
            speaker_log_probs, _, sample = self.speaker0.sample(data, alt_data, dropout, viterbi=False)

            fake_scenes = []
            for i in range(len(data)):
                fake_scenes.append(data[i]._replace(fake_scenes, alt_data, dropout)) # do I need dropout here
            all_fake_scenes.append(fake_scenes)

            listener_logprobs = self.listener0.forward(fake_scenes, alt_data, dropout) # dropout"
            speaker_scores[:, i_sample] = speaker_log_probs
            listener_scores[:, i_sample] = listener_log_probs

        scores = listener_scores

        out_sentences = []
        out_speaker_scores = np.zeros(len(data))
        out_listener_scores = np.zeros(len(data))

        for i in range(len(data)):
            if viterbi:
                q = scores[i, :].argmax()
            elif quantile is not None:
                idx = int(n_samples * quantile)
                if idx == n_samples:
                    q = scores.argmax()
                else:
                    q = scores[i,:].argsort()[idx]
            else:
                q = 0
            out_sentences.append(all_fake_scenes[q][i].description)
            out_speaker_scores[i] = speaker_scores[i][q]
            out_listener_scores[i] = listener_scores[i][q]

        return out_speaker_scores, out_listener_scores, out_sentences

class CompiledSpeaker1Model(nn.Module):
    def __init__(self, vocab_sz, hidden_sz, dropout): #figure out what parameters later
        super(CompiledSpeaker1Model, self).__init__()
        self.vocab_sz = vocab_sz
        self.hidden_sz = hidden_sz

        self.scene_input_sz = N_PROP_TYPES * N_PROP_OBJECTS

        self.sampler = SamplingSpeaker1Model() # send params
        self.scene_encoder = LinearSceneEncoder("CompSpeaker1Model", self.scene_input_sz, hidden_sz)
        self.string_decoder = MLPStringDecoder("CompSpeaker1Model")

        self.fc = nn.Linear() # maybe??
        self.dropout_p = dropout

    def forward(self, data, alt_data):
        _, _, samples = self.sampler.sample(data, alt_data, self.dropout_p, True)

        scene_enc = self.scene_encoder.forward("true", data, self.dropout_p)
        alt_scene_enc = [self.scene_encoder.forward("alt%d" % i, alt, self.dropout_p)
                            for i, alt in enumerate(alt_data)]

        ### figure out how to translate these lines
        l_cat = "CompSpeaker1Model_concat"
        self.apollo_net.f(Concat(
            l_cat, bottoms=[scene_enc] + alt_scene_enc))
        ###

        fake_data = [d._replace(description=s) for d, s in zip(data, samples)]

        losses = self.string_decoder.forward("", l_cat, fake_data, self.dropout_p)
        return losses, np.asarray(0)

    def sample(self, data, alt_data, viterbi, quantile=None):
        scene_enc = self.scene_encoder.forward("true", data, self.dropout_p)
        alt_scene_enc = [self.scene_encoder.forward("alt%d" % i, alt, self.dropout_p)
                            for i, alt in enumerate(alt_data)]
        ### figure out how to translate these lines
        l_cat = "CompSpeaker1Model_concat"
        self.apollo_net.f(Concat(
            l_cat, bottoms=[scene_enc] + alt_scene_enc))
        ###

        probs, sample = self.string_decoder.sample("", l_cat, viterbi)
        return probs, np.zeros(probs.shape), sample

class LinearStringEncoder(nn.Module):
    def __init__(self, name, vocab_sz, hidden_sz, dropout): #figure out what parameters later
        super(LinearStringEncoder, self).__init__()
        self.name = name
        self.vocab_sz = vocab_sz
        self.hidden_sz = hidden_sz
        self.fc = nn.Linear(vocab_sz, hidden_sz)
        self.dropout = dropout

    def forward(self, scenes):
        feature_data = Variable(torch.zeros(len(scenes), self.vocab_sz))
        if torch.cuda.is_available():
            feature_data = feature_data.cuda()

        for i_scene, scene in enumerate(scenes):
            for word in scene.description:
                feature_data[i_scene, word] = feature_data[i_scene, word] + 1 # for some reason += is buggy
        # print("LinearStringEncoder_" + prefix)
        # print("LinearStringEncoder_")

        result = self.fc(feature_data)
        return result

class LinearSceneEncoder(nn.Module):
    def __init__(self, name, input_sz, hidden_sz, dropout): #figure out what parameters later
        super(LinearSceneEncoder, self).__init__()
        self.name = name
        self.input_sz = input_sz
        self.hidden_sz = hidden_sz
        self.fc = nn.Linear(input_sz, hidden_sz)
        self.dropout_p = dropout

    def forward(self, scenes):
        feature_data = Variable(torch.zeros(len(scenes), N_PROP_TYPES * N_PROP_OBJECTS))
        if torch.cuda.is_available():
            feature_data = feature_data.cuda()

        for i_scene, scene in enumerate(scenes):
            for prop in scene.props:
                feature_data[i_scene, prop.type_index * N_PROP_OBJECTS +
                        prop.object_index] = 1
        # print("LinearSceneEncoder_" + prefix)
        # print("LinearSceneEncoder_")
        result = self.fc(feature_data)
        return result

class LSTMStringDecoder(nn.Module):
    def __init__(self, name, vocab_sz, embedding_dim, hidden_sz, dropout, num_layers=2): #figure out what parameters later
        super(LSTMStringDecoder, self).__init__()
        self.name = name
        self.vocab_sz = vocab_sz
        self.embedding_dim = embedding_dim
        self.hidden_sz = hidden_sz
        self.num_layers = num_layers

        self.dropout_p = dropout

        self.embedding = nn.Embedding(vocab_sz, embedding_dim)
        self.lstm = nn.LSTM(embedding_dim, hidden_sz, num_layers, dropout=self.dropout_p)
        self.linear = nn.Linear(hidden_sz, vocab_sz)
        self.dropout = nn.Dropout(self.dropout_p)
        self.init_weights()

    def init_weights(self):
        self.embedding.weight.data.uniform_(-self.init_param, self.init_param)
        self.linear.weight.data.uniform_(-self.init_param, self.init_param)

    def init_hidden(self, batch_size=100):
        if torch.cuda.is_available():
            return (Variable(torch.zeros(self.num_layers, batch_size, self.hidden_sz)).cuda(),
            Variable(torch.zeros(self.num_layers, batch_size, self.hidden_sz)).cuda())

        return (Variable(torch.zeros(self.num_layers, batch_size, self.hidden_sz)),
            Variable(torch.zeros(self.num_layers, batch_size, self.hidden_sz)))

    def forward(self, scenes): # why do you need encoding or prefix? QUESTION
        max_words = max(len(scene.description) for scene in scenes)
        word_data = Variable(torch.zeros(len(scenes), max_words))

        if torch.cuda.is_available():
            word_data = word_data.cuda()

        for i_scene, scene in enumerate(scenes):
            offset = max_words - len(scene.description)
            for i_word, word in enumerate(scene.description):
                word_data[i_scene, i_word] = word

        # print("LSTMStringDecoder_" + prefix)
        # print("LSTMStringDecoder_")

        hidden = init_hidden()
        embedding = self.embedding(word_data) # find out dimensions of word_data
        output, hidden = self.lstm(embedding, hidden)
        output = self.dropout(output)
        output = self.linear(output.view(-1, self.hidden_sz))
        return output, hidden

class MLPScorer(nn.Module):
    def __init__(self, name, hidden_sz, output_sz, dropout): #figure out what parameters later
        super(MLPScorer, self).__init__()
        self.name = name
        self.output_sz = output_sz
        self.hidden_sz = hidden_sz # hidden_sz refers to the encoding size?
        self.dropout_p = dropout

        self.intermediate_sz = hidden_sz # not sure..

        self.linear_4 = nn.Linear(hidden_sz, self.intermediate_sz) # Referent (scene) encodings
        self.linear_5 = nn.Linear(hidden_sz, self.intermediate_sz) # String encodings
        self.linear_3 = nn.Linear(self.intermediate_sz, 1) # what size is this supposed to be?


    def forward(self, query, targets, labels): # string_enc, scenes, labels
        # print("MLPScorer_" + prefix)
        # print("MLPScorer_")

        # targets = scenes? each is [100 x 50] = batch_size x hidden_sz -> 
        num_targets = len(targets) # 2 

        targets_after_linear = [self.linear_4(target).unsqueeze(1) for target in targets]
        targets = torch.cat(targets_after_linear, dim=1)

        string_enc = self.linear_5(query).unsqueeze(1) # w_5 * e_d

        linear_combination = targets + string_enc # batch_sz x 2 x output?

        post_relu = F.relu(linear_combination)

        ss = self.linear_3(post_relu).squeeze() # [batch_size x 2] after squeeze

        return ss

        # should we output the log softmaxes???
        return F.log_softmax(ss, dim=1).squeeze() #i guess not for cross entropy

        # # query.unsqueeze_(1) # should be batch_sz, 1, n_dims = 50 (hidden size)
        # new_query = query.expand(-1, num_targets)
        # new_sum = new_query + targets # element wise summation. MAY NOT WORK

        # result = self.linear(new_sum).squeeze(1) # should now be batch_sz, n_dims
        # return result

class MLPStringDecoder(nn.Module):
    def __init__(self, name, input_sz, hidden_sz, vocab_sz, dropout):
        super(MLPStringDecoder, self).__init__()
        self.net = nn.Sequential(
            nn.Linear(input_sz, hidden_sz),
            nn.Linear(hidden_sz, hidden_sz),
            nn.Linear(hidden_sz, vocab_sz),
            nn.Dropout(dropout)
            )

    def forward(self, scene_enc, scenes):
        pdb.set_trace()
        max_words = max(len(scene.description) for scene in scenes)

        word_data = Variable(torch.zeros(len(scenes), max_words))

        if torch.cuda.is_available():
            word_data = word_data.cuda()

        for i_scene, scene in enumerate(scenes):
            offset = max_words - len(scene.description)
            for i_word, word in enumerate(scene.description):
                word_data[i_scene, i_word] = word

        output = self.net(word_data)
        return output




