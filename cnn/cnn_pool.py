#encoding:utf-8
#导入模块
import torch 
import torch.utils.data as D
from torch.autograd import Variable
import numpy as np
import torch.nn.functional as F
from sklearn.model_selection import KFold
#参数设置
DW=200
N=123
DP=25
NP=123
NR=19
DC=1000
KP=0.5
K=3
LR=0.01
BATCH_SIZE=2
epochs=300
#making data
#load_data include train.txt,test.txt
def load_data(src):
    sentences=[]
    relations=[]
    e1_pos=[]
    e2_pos=[]
    with open(src,'r') as f:
        for line in f:
            line=line.strip().decode('utf-8')
            if line:
                tmp=line.split()
                relations.append(int(tmp[0]))
                e1_pos.append((int(tmp[1]),int(tmp[2])))
                e2_pos.append((int(tmp[3]),int(tmp[4])))
                sentences.append(tmp[5:])
    return sentences,relations,e1_pos,e2_pos
train_data=load_data('train.txt')
test_data=load_data('test.txt')

#build dict
from collections import Counter
def build_dict(sentences):
    word_count=Counter()
    for sent in sentences:
        for w in sent:
            word_count[w]+=1
    ls=word_count.most_common()
    word_dict={w[0]:index+1 for (index,w) in enumerate(ls)}
    return word_dict
word_dict=build_dict(train_data[0])

#compute distance
def pos(x):
    '''
    map the relative distance between [0, 123)
    '''
    if x < -60:
        return 0
    if x >= -60 and x <= 60:
        return x + 61
    if x > 60:
        return 122
#vector word
def vectorize(data, word_dict, max_len):
    sentences, relations, e1_pos, e2_pos = data
    e1_vec = []
    e2_vec = []
    num_data = len(sentences)
    sents_vec = np.zeros((num_data, max_len), dtype=int)
    
    for idx, (sent, pos1, pos2) in enumerate(zip(sentences, e1_pos, e2_pos)):
        vec = [word_dict[w] if w in word_dict else 0 for w in sent]
        sents_vec[idx, :len(vec)] = vec

        e1_vec.append(vec[pos1[1]])
        e2_vec.append(vec[pos2[1]])

    # compute relative distance
    dist1 = []
    dist2 = []

    for sent, p1, p2 in zip(sents_vec, e1_pos, e2_pos):
        # current word position - last word position of e1 or e2
        dist1.append([pos(p1[1] - idx) for idx, _ in enumerate(sent)])
        dist2.append([pos(p2[1] - idx) for idx, _ in enumerate(sent)])
    #print sents_vec.size

    return sents_vec, relations, e1_vec, e2_vec, dist1, dist2

x, y, e1, e2, dist1, dist2 = vectorize(train_data, word_dict, N)
y = np.array(y).astype(np.int64)
print y.shape
np_cat = np.concatenate((x, np.array(e1).reshape(-1, 1), 
                         np.array(e2).reshape(-1, 1), 
                         np.array(dist1), 
                         np.array(dist2)),1)
print np_cat.shape
print len(e1),len(e2)
#make test_data,eval_data
tx, ty, te1, te2, td1, td2 = vectorize(test_data, word_dict, N)
y = np.array(y).astype(np.int64)
eval_cat = np.concatenate((tx, np.array(te1).reshape(-1, 1),
                           np.array(te2).reshape(-1, 1),
                           np.array(td1), 
                           np.array(td2)), 1)
#laod embedding
def load_embedding(emb_file, emb_vocab, word_dict):
    vocab = {}
    with open(emb_vocab, 'r') as f:
        #for id, w in enumerate(f.readlines()):
        for line in f:
            line=line.strip().lower().decode('utf-8')
            if line:
                vocab[line]=len(vocab)
    f_e=open(emb_file,'r')
    embed=f_e.readlines()
    dim=len(embed[0].split())
    embeddings=np.random.uniform(-0.01,0.01,size=(len(word_dict)+1,dim))
    for w in vocab:
        if w in word_dict:
            embeddings[word_dict[w]]=[float(x) for x in embed[vocab[w]].split()]
    embeddings[0]=np.zeros(dim)
    f_e.close()
    return embeddings.astype(np.float32)
embed_file = 'embeddings.txt'
vac_file = 'words.lst'
embedding = load_embedding(embed_file, vac_file, word_dict)
print embedding.shape
#make model
from torch import nn
import torch.nn.functional as F
def one_hot(indices, depth, on_value=1, off_value=0):
    #print indices
    np_ids = np.array(indices.cpu().data.numpy()).astype(int)
    #print len(np_ids.shape)
    if len(np_ids.shape) == 2:
        encoding = np.zeros([np_ids.shape[0], np_ids.shape[1], depth], dtype=int)
        added = encoding + off_value
        for i in range(np_ids.shape[0]):
            for j in range(np_ids.shape[1]):
                added[i, j, np_ids[i, j]] = on_value
        return Variable(torch.FloatTensor(added.astype(float))).cuda()
    if len(np_ids.shape) == 1:
        encoding = np.zeros([np_ids.shape[0], depth], dtype=int)
        added = encoding + off_value
        for i in range(np_ids.shape[0]):
            added[i, np_ids[i]] = on_value
        return Variable(torch.FloatTensor(added.astype(float))).cuda()
    
class ACNN(nn.Module):
    def __init__(self, max_len, embedding, pos_embed_size,
                 pos_embed_num, slide_window, class_num,
                 num_filters, keep_prob):
        super(ACNN, self).__init__()
        #embed_dim
        self.dw = embedding.shape[1]
        #words_num
        self.vac_len = embedding.shape[0]
        #pos_dim
        self.dp = pos_embed_size
        #concatenate word_dim and pos_dim
        self.d = self.dw + 2 * self.dp
        #pos_num
        self.np = pos_embed_num
        #relation numbers
        self.nr = class_num
        #fileters num
        self.dc = num_filters
        #dropout 
        self.keep_prob = keep_prob
        #slide_window size
        self.k = slide_window
        #padding size
        self.p = (self.k - 1) // 2
        #sentence length
        self.n = max_len
        #concatenate vector size
        self.kd = self.d * self.k
        #e1,e2,x embedding
        self.x_embedding = nn.Embedding(self.vac_len, self.dw)
        self.x_embedding.weight = nn.Parameter(torch.from_numpy(embedding))
        #pos embedding
        self.dist1_embedding = nn.Embedding(self.np, self.dp)
        self.dist2_embedding = nn.Embedding(self.np, self.dp)
        
        #
        self.pad = nn.ConstantPad2d((0, 0, self.p, self.p), 0)
        self.y_embedding = nn.Embedding(self.nr, self.dc)
        self.dropout = nn.Dropout(self.keep_prob)
        self.conv = nn.Conv2d(1, self.dc, (self.k, self.kd), (1, self.kd), (self.p, 0), bias=True)
        self.tanh = nn.Tanh()
        self.max_pool = nn.MaxPool2d((1, self.dc), (1, self.dc))
        self.softmax = nn.Softmax()
		self.fc1=nn.Linear(self.n,self.nr)
    #生成滑动窗口矩阵
    def window_cat(self, x_concat):
        s = x_concat.data.size()
        #print s
        px = self.pad(x_concat.view(s[0], 1, s[1], s[2])).view(s[0], s[1] + 2 * self.p, s[2])
        #print px.size()
        t_px = torch.index_select(px, 1, Variable(torch.LongTensor(range(s[1]))).cuda())
        m_px = torch.index_select(px, 1, Variable(torch.LongTensor(range(1, s[1] + 1))).cuda())
        b_px = torch.index_select(px, 1, Variable(torch.LongTensor(range(2, s[1] + 2))).cuda())
        #print t_px.size()
        return torch.cat([t_px, m_px, b_px], 2)

		
	def forward(self,x,e1,e2,dist1,dist2,is_training=True):
		bz = x.data.size()[0]
		x_embed = self.x_embedding(x) # (bz, n, dw)
        dist1_embed = self.dist1_embedding(dist1)
        dist2_embed = self.dist2_embedding(dist2)
        x_concat = torch.cat((x_embed, dist1_embed, dist2_embed), 2)
        w_concat = self.window_cat(x_concat)
        if is_training:
            w_concat = self.dropout(w_concat)
		s = w_concat.data.size()  # bz, n, k*d
        R = self.tanh(self.conv(w_concat.view(s[0], 1, s[1], s[2]))) # bz, dc, n, 1
        #print s,R.size()
        R_star = R.view(s[0], self.dc, s[1])
		R_star=self.max_pool(wo.view(bz,1,self.nr,self.dc)).sequeeze(2)
		R_star=self.fc1(R_star)
		R_star=self.softmax(R_star)
		return R_star


#train 
model = ACNN(N, embedding, DP, NP, K, NR, DC, KP).cuda()
print model
#optimizer = torch.optim.SGD(model.parameters(), lr=LR)  # optimize all rnn parameters
optimizer = torch.optim.Adam(model.parameters())  # optimize all rnn parameters
#loss_func = NovelDistanceLoss(NR)
loss_func=torch.nn.CrossEntropy()

def data_unpack(cat_data, target):
    list_x = np.split(cat_data.numpy(), [N, N + 1, N + 2, N + 2 + NP], 1)
    #np.split(x,[p1,p2,p3,p4,...],dim)表示第几列
    bx = Variable(torch.from_numpy(list_x[0])).cuda()
    be1 = Variable(torch.from_numpy(list_x[1])).cuda()
    be2 = Variable(torch.from_numpy(list_x[2])).cuda()
    bd1 = Variable(torch.from_numpy(list_x[3])).cuda()
    bd2 = Variable(torch.from_numpy(list_x[4])).cuda()
    target = Variable(target).cuda()
    return bx, be1, be2, bd1, bd2, target

#making data
train=torch.from_numpy(np_cat.astype(np.int64))
y_tensor=torch.LongTensor(y)
train_datasets=D.TensorDataset(data_tensor=train,target_tensor=y_tensor)
train_dataloader=D.DataLoader(train_datasets,BATCH_SIZE,True,num_workers=2)

eval = torch.from_numpy(eval_cat.astype(np.int64))
y_tensor = torch.LongTensor(ty)
eval_datasets = D.TensorDataset(data_tensor=eval, target_tensor=y_tensor)
eval_dataloader = D.DataLoader(eval_datasets, BATCH_SIZE, True, num_workers=2)

def prediction(out,y):
	predict=torch.max(out,1)[1].long()
	correct=torch.eq(predict,by)
	acc=correct.sum().float()/float(correct.data.size()[0])
	return acc
#train
for i in range(epochs):
    acc = 0
    j = 0
	eval_acc = 0
    eval_j = 0
    for (x_cat, ty) in train_dataloader:
        bx, be1, be2, bd1, bd2, by = data_unpack(x_cat, ty)
        out = model(bx, be1, be2, bd1, bd2)
		acc+=prediction(out,by)
		loss=loss_func(out,by)
		optimizer.zero_grad()
		loss.backward()
		optimizer.step()
        j += 1
    for (b_x_cat, b_y) in eval_dataloader:
        bx, be1, be2, bd1, bd2, by = data_unpack(b_x_cat, b_y)
        wo, rel_weight = model(bx, be1, be2, bd1, bd2, False)
        eval_acc+=prediction(out,by)
        eval_j += 1
    #print acc,j,acc/(j*50),eval_acc,ti,eval_acc/(ti*50)
    print 'epoch:', i, 'acc:', acc / j, '%   loss:', loss.cpu().data.numpy()[0] / j, 'test_acc:', eval_acc / eval_j, '%'
	if i%10==0:
		torch.save(model.state_dict(), 'cnn_pool.pkl')













