#-*- coding:utf-8 -*-

import os
import numpy as np
import tensorflow as tf

from collections import Counter
import pandas as pd

from tqdm import tqdm
import random
import pickle
from tools.timer import log_time_delta

from nltk.corpus import stopwords
Overlap = 237
import random
from units import to_array 
class Alphabet(dict):
    def __init__(self, start_feature_id = 1):
        self.fid = start_feature_id

    def add(self, item):
        idx = self.get(item, None)
        if idx is None:
            idx = self.fid
            self[item] = idx
      # self[idx] = item
            self.fid += 1
        return idx

    def dump(self, fname):
        with open(fname, "w") as out:
            for k in sorted(self.keys()):
                out.write("{}\t{}\n".format(k, self[k]))

           
class BucketIterator(object):
    def __init__(self,data,always=False,opt=None,batch_size=2,max_sequence_length=0,shuffle=True,test=False,position=False,backend="keras"):
        self.shuffle=shuffle
        self.data=data
        self.batch_size=batch_size
        self.test=test 
        self.backend=backend
        self.transform=self.setTransform()
        self.always=always
        self.max_sequence_length = max_sequence_length
        
        if opt is not None:
            self.setup(opt)
            
    def setup(self,opt):
        
        self.batch_size=opt.batch_size
        self.shuffle=opt.__dict__.get("shuffle",self.shuffle)
#        self.position=opt.__dict__.get("position",False)
        self.transform=self.setTransform()
        
    def setTransform(self):
        if self.backend == "tensorflow":
            return self.transformTF
        elif self.backend == "torch":
            return  self.transformTorch
        else:
            return  self.transformKeras
            
    
    def transformTorch(self,data):
        if torch.cuda.is_available():
            data=data.reset_index()
            text= Variable(torch.LongTensor(data.text).cuda())
            label= Variable(torch.LongTensor([int(i) for i in data.label.tolist()]).cuda())                
        else:
            data=data.reset_index()
            text= Variable(torch.LongTensor(data.text))
            label= Variable(torch.LongTensor(data.label.tolist()))
        if self.position:
            position_tensor = self.get_position(data.text)
            return DottableDict({"text":(text,position_tensor),"label":label})
        return DottableDict({"text":text,"label":label})
    
    def transformKeras(self,data):
        return [to_array(i,self.max_sequence_length) if type(i[0])!=int and type(i)!=np.ndarray  else i for i in data]
    def transformTF(self,data):
        return [to_array(i,self.max_sequence_length) if type(i[0])!=int and type(i)!=np.ndarray  else i for i in data]
    
#    def get_position(self,inst_data):
#        inst_position = np.array([[pos_i+1 if w_i != self.padding_token else 0 for pos_i, w_i in enumerate(inst)] for inst in inst_data])
#        inst_position_tensor = Variable( torch.LongTensor(inst_position), volatile=self.test) 
#        if torch.cuda.is_available():
#            inst_position_tensor=inst_position_tensor.cuda()
#        return inst_position_tensor

    def __iter__(self):
        if self.shuffle and not self.test:
#            random.shuffle(self.data)
            c = list(zip(*self.data))
            random.shuffle(c)
            self.data = [i for i in zip(*c)]
#            self.data = self.data.sample(frac=1).reset_index(drop=True)          
            
#        if sort_by_len:
#            sorted_index = sorted(range(len(q)), key=lambda x: len(q[x]), reverse=True)
#            q = [ q[i] for i in sorted_index]
#            a = [a[i] for i in sorted_index]
#            neg_a = [ neg_a[i] for i in sorted_index]
            
        batch_nums = int(len(self.data[0])/self.batch_size)

        if len(self.data)%self.batch_size!=0:
            batch_nums=1+batch_nums
        indexes = [(i*self.batch_size,(i+1)*self.batch_size) for  i in range(batch_nums)]

        for index in indexes:

            yield self.transform([item[index[0]:index[1]] for item in self.data])



class dataHelper():
    def __init__(self,opt):
        for key,value in opt.__dict__.items():
            self.__setattr__(key,value)        
      
            
        dir_path = os.path.join(os.path.join(opt.datasets_dir, "QA"),opt.dataset_name.lower())
        self.datas = self.load(dir_path,filter = opt.clean)
        self.alphabet = self.get_alphabet(self.datas.values())
        self.optCallback(opt)            
            
    def optCallback(self,opt):
        q_max_sent_length = max(map(lambda x:len(x),self.datas["train"]['question'].str.split()))
        a_max_sent_length = max(map(lambda x:len(x),self.datas["train"]['answer'].str.split()))    
        self.max_sequence_length = max(q_max_sent_length,a_max_sent_length)
        
        print('get embedding')
        if opt.dataset_name=="NLPCC":     # can be updated
            self.embeddings = self.get_embedding(language="cn",fname=opt.wordvec_path)
        else:
            self.embeddings = self.get_embedding(fname=opt.wordvec_path)
        opt.embeddings = self.embeddings
        opt.nb_classes = 2               # for nli, this could be 3
        opt.alphabet=self.alphabet
        opt.embedding_size = self.embeddings.shape[1]
        opt.max_sequence_length=self.max_sequence_length
        opt.lookup_table = self.embeddings      
        
            
    def load(self, data_dir, filter = True):
        datas = dict()
        for data_name in ["train",'test']: #'dev'            
            data_file = os.path.join(data_dir,data_name+".txt")
            data = pd.read_csv(data_file,header = None,sep="\t",names=["question","answer","flag"]).fillna('0')
    #        data = pd.read_csv(data_file,header = None,sep="\t",names=["question","answer","flag"],quoting =3).fillna('0')
            
            if filter == True:
                datas[data_name]=self.removeUnanswerdQuestion(data)
            else:
                datas[data_name]=data
        return datas
    
    @log_time_delta
    def removeUnanswerdQuestion(self,df):
        counter= df.groupby("question").apply(lambda group: sum(group["flag"]))
        questions_have_correct=counter[counter>0].index
        counter= df.groupby("question").apply(lambda group: sum(group["flag"]==0))
        questions_have_uncorrect=counter[counter>0].index
        counter=df.groupby("question").apply(lambda group: len(group["flag"]))
#        questions_multi=counter[counter>1].index
    
        return df[df["question"].isin(questions_have_correct) &  df["question"].isin(questions_have_correct) & df["question"].isin(questions_have_uncorrect)].reset_index()

                
    def get_alphabet(self,corpuses=None,dataset=""):
        pkl_name="temp/"+self.dataset_name+".alphabet.pkl"
        if  os.path.exists(pkl_name):
            return pickle.load(open(pkl_name,"rb"))
        alphabet = Alphabet(start_feature_id = 0)
        alphabet.add('[UNK]')  
#        alphabet.add('END') 
        for corpus in corpuses:
            for texts in [corpus["question"].unique(),corpus["answer"]]:    
                for sentence in texts:                   
                    tokens = sentence.lower().split()
                    for token in set(tokens):
                        alphabet.add(token)
            print("alphabet size %d" % len(alphabet.keys()) )
        if not os.path.exists("temp"):
            os.mkdir("temp")
        pickle.dump( alphabet,open(pkl_name,"wb"))
        return alphabet   
    

    @log_time_delta
    def get_embedding(self,fname=None,language ="en", fresh = True):
        pkl_name="temp/"+self.dataset_name+".subembedding.pkl"
        if  os.path.exists(pkl_name) and not fresh:
            return pickle.load(open(pkl_name,"rb"))
#        if language=="en":
#            fname = 'embedding/glove.6B/glove.6B.300d.txt'
#        else:
#            fname= "embedding/embedding.200.header_txt"
        embeddings,embedding_size = self.load_text_vec(fname)
        sub_embeddings = self.getSubVectorsFromDict(embeddings,embedding_size)
        self.embedding_size=embedding_size
        pickle.dump( sub_embeddings,open(pkl_name,"wb"))
        return sub_embeddings
    

    def getSubVectorsFromDict(self,vectors,dim = 300):
        vocab= self.alphabet
        embedding = np.zeros((len(vocab),dim))
        count = 1
        for word in vocab:
            if word in vectors:
                count += 0
                embedding[vocab[word]]= vectors[word]
            else:
                embedding[vocab[word]]= np.random.uniform(-0.5,+0.5,dim)#vectors['[UNKNOW]'] #.tolist()
        print( 'word in embedding',count)
        print( 'word not in embedding',len(vocab)-count)
        return embedding
    
    def encode_to_split(self,sentence):    
        
        tokens = sentence.lower().split()[:self.max_sequence_length]   # tokens = [w for w in tokens if w not in stopwords.words('english')]
        seq = [self.alphabet[w] if w in self.alphabet else self.alphabet['[UNK]'] for w in tokens]
#        seq_pos = np.array([[pos_i+1 if w_i != self.padding_token else 0 for pos_i, w_i in enumerate(inst)] for inst in inst_data])
        
        
        return seq
    
    @log_time_delta
    def load_text_vec(self,filename=""):
        vectors = {}
        with open(filename,encoding='utf-8') as f:
            i = 0
            for line in f:
                i += 1
                if i % 100000 == 0:
                    print( 'epch %d' % i)
                items = line.strip().split(' ')
                if len(items) == 2:
                    vocab_size, embedding_size= items[0],items[1]
                    print( ( vocab_size, embedding_size))
                else:
                    word = items[0]
                    if word in self.alphabet:
                        vectors[word] = items[1:]
        embedding_size = len(items[1:])
        print( 'embedding_size',embedding_size)
        print( 'done')
        print( 'words found in wor2vec embedding ',len(vectors.keys()))
        return vectors,embedding_size
    
#    @log_time_delta
    def getTrain(self,sort_by_len = True,shuffle = True,model=None,sess=None,overlap_feature= False,iterable=True,max_sequence_length=0):
        
        q,a,neg_a,overlap1,overlap2 = [],[],[],[],[]
        for question,group in self.datas["train"].groupby("question"):
            pos_answers = group[group["flag"] == 1]["answer"]
            neg_answers = group[group["flag"] == 0]["answer"]#.reset_index()
            if len(pos_answers)==0 or  len(neg_answers)==0:
    #            print(question)
                continue
            for pos in pos_answers:                
                if model is not None and sess is not None:                    
                    pos_sent= self.encode_to_split(pos)
                    q_sent,q_mask= self.prepare_data([pos_sent])                             
                    neg_sents = [self.encode_to_split(sent) for sent in neg_answers ]
                    a_sent,a_mask= self.prepare_data(neg_sents)                   
      
                    scores = model.predict(sess,(np.tile(q_sent,(len(neg_answers),1)),a_sent))
                    neg_index = scores.argmax()   
                    seq_neg_a = neg_sents[neg_index]
                else:    
#                    if len(neg_answers.index) > 0:
                    neg_index = np.random.choice(neg_answers.index)
                    neg = neg_answers.loc[neg_index,]
                    seq_neg_a = self.encode_to_split(neg)
                
                seq_q = self.encode_to_split(question)
                seq_a = self.encode_to_split(pos)
                
                q.append(seq_q)
                a.append(seq_a)
                neg_a.append(seq_neg_a)
                if overlap_feature :
                    overlap1.append(self.overlap_index(seq_q,seq_a))
                    overlap2.append(self.overlap_index(seq_q,seq_neg_a))
        if  overlap_feature :
            data= (q,a,neg_a,overlap1,overlap2)
        else:
            data = (q,a,neg_a)
        
        if iterable:
            return BucketIterator( data,batch_size=self.batch_size,shuffle=True,max_sequence_length=max_sequence_length) 
        else: 
            return data
    # calculate the overlap_index
    def overlap_index(self,question,answer,stopwords = []):

        qset = set(question)
        aset = set(answer)
        a_len = len(answer)
    
        # q_index = np.arange(1,q_len)
        a_index = np.arange(1,a_len + 1)
    
        overlap = qset.intersection(aset)
        # for i,q in enumerate(cut(question)[:q_len]):
        #     value = 1
        #     if q in overlap:
        #         value = 2
        #     q_index[i] = value
        for i,a in enumerate(answer):
            if a in overlap:
                a_index[i] = Overlap
        return a_index

    

            
    def getTest(self,mode ="test",overlap_feature =False, iterable = True):
        
        if overlap_feature:
            process = lambda row: (self.encode_to_split(row["question"]),
                               self.encode_to_split(row["answer"]), 
                               self.overlap_index(row['question'],row['answer'] ))
        else:
            process = lambda row: (self.encode_to_split(row["question"]),
                               self.encode_to_split(row["answer"]))
        
        samples = self.datas[mode].apply( process,axis=1)
        if iterable:
            return BucketIterator( [i for i in zip(*samples)],batch_size=self.batch_size,shuffle=False)
        else: 
            return [i for i in zip(*samples)]
        
    def getPointWiseSamples4Keras(self, iterable = False):
        while True:
            for batch in self.getTrain(iterable=True,max_sequence_length=self.max_sequence_length):
                q,a,neg = batch
                data = [[np.concatenate([q,q],0),np.concatenate([a,neg],0)],
                        [1]*len(q) +[0]*len(q)]
                yield data
#        c = list(zip(*data))
#        random.shuffle(c)
#        
##            print(type(item))
#        result = [to_array(item,self.max_sequence_length) if i<2 else np.array(item)  for i,item in enumerate(zip(*c))]
#        if iterable:            
#            x,y,z = result
#            formated = ([i for i in zip(x,y)],z)
#            return BucketIterator(formated,batch_size=self.batch_size,shuffle=False,max_sequence_length = self.max_sequence_length)
#        else:
#            return result
        
    
    
    def getPairWiseSamples4Keras(self, iterable = False):
        
        while True:
            for batch in self.getTrain(iterable=True,max_sequence_length=self.max_sequence_length):
                yield batch,batch
        
        
#        data = [q,a,neg]
#        c = list(zip(*data))
#        random.shuffle(c)
#        
##            print(type(item))
#        result = [to_array(item,self.max_sequence_length) for i,item in enumerate(zip(*c))]
#        return result
        
            
    def prepare_data(self,seqs):
        lengths = [len(seq) for seq in seqs]
        n_samples = len(seqs)
        max_len = np.max(lengths)
    
        x = np.zeros((n_samples, max_len)).astype('int32')
        x_mask = np.zeros((n_samples, max_len)).astype('float')
        for idx, seq in enumerate(seqs):
            x[idx, :lengths[idx]] = seq
            x_mask[idx, :lengths[idx]] = 1.0
         # print( x, x_mask)
        return x, x_mask
        

if __name__ == "__main__":
    
    
#    from dataset import qa
#    from params import Params
#    
#    params = Params()
#    config_file = 'config/qa.ini'    # define dataset in the config
#    params.parse_config(config_file)
#    
#    reader = qa.setup(params)
##    data1 = next(iter(reader.getTest()))
##    data = next(iter(reader.getTrain(overlap_feature=True)))
##    for data in reader.getTest(overlap_feature=True,shuffle=False):
##        print(len(data))
##    data = next(iter(reader.getTrain(overlap_feature=True,shuffle=False)))
##    data = next(iter(reader.getTest(overlap_feature=True)))
#    data = reader.getTrain(iterable=False)
    # -*- coding: utf-8 -*-
    import keras
    from keras.layers import Input, Dense, Activation, Lambda
    import numpy as np
    from keras import regularizers
    from keras.models import Model
    import sys
    from params import Params
    from dataset import qa
    import keras.backend as K
    import units
    from loss import *

    from models.match import keras as models
    from params import Params
    params = Params()

    config_file = 'config/qalocal.ini'    # define dataset in the config
    params.parse_config(config_file)
    
    reader = qa.setup(params)
    qdnn = models.setup(params)
    model = qdnn.getModel()
    
    from loss import *
    model.compile(loss = rank_hinge_loss({'margin':0.2}),
                optimizer = units.getOptimizer(name=params.optimizer,lr=params.lr),
                metrics=['accuracy'])
    model.summary()
    
    
    
    
#    generators = [reader.getTrain(iterable=False) for i in range(params.epochs)]
#    [q,a,score] = reader.getPointWiseSamples()
#    model.fit(x = [q,a,a],y = [q,a,q],epochs = 10,batch_size =params.batch_size)
    
#    def gen():
#        while True:
#            for sample in reader.getTrain(iterable = True):
#                yield sample
    model.fit_generator(reader.getPointWiseSamples4Keras(),epochs = 20,steps_per_epoch=1000)

