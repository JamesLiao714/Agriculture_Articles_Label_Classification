import json
import numpy as np
import torch
import os
import glob
import sys
from transformers import AutoTokenizer
from random import sample
from math import ceil
from tqdm import tqdm
import argparse
import pickle
import ast

### todo
# same word dict 不能重複 會被改道 青青蔥 done
# ckiptagger force done
# inbatch negative
# use colbert's bert train classifier


# data augment 替換時間地點事件、keywords


### rule
# TFIDF



def create_same_words_dict():
    import pandas as pd
    files = glob.glob("./data/Keywords/*.xlsx")
    same_words_dict = {}

    for file in files:
        df = pd.read_excel(file, header=None)
        df_list = df.values.tolist()
        for words in df_list:
            change_to = words[0]
            for word in words:
                word = str(word)
                if word == 'nan':
                    break
                if word != change_to:
                    same_words_dict[word] = change_to
    
    return same_words_dict
                
    

def create_train_json(json_path, folder_path):
    files = glob.glob(f"{folder_path}*.txt")

    print(len(files))

    results = []
    for file in files:
        did =  file.split('/')[-1].split('.')[0]
        with open(file, 'r') as f:
            title, *texts = f.readlines()
            title = title.strip()
            texts = [text.strip() for text in texts]
            text = ''.join(texts)
            json_data = {
                'did' : did,
                'title' : title,
                'text' : text
            }
            results.append(json_data)
    with open(json_path, 'w', encoding='utf8') as f:
	    json.dump(results, f, ensure_ascii=False)




def create_positive_dict():
    try:
        with open('./data/train_positive_dict', 'rb') as handle:
            positive_dict = pickle.load(handle)
        return positive_dict
    except:
        positive_dict = {}
        import csv
        f = open('./data/TrainLabel.csv', 'r')
        rows = csv.reader(f, delimiter=',')
        for row in rows:
            test_id , ref_id = row
            if test_id == 'Test':
                continue
            if test_id in positive_dict:
                positive_dict[test_id].append(ref_id)
            else:
                positive_dict[test_id] = [ref_id]
        f.close()
        with open('./data/train_positive_dict', 'wb') as handle:
            pickle.dump(positive_dict, handle, protocol=pickle.HIGHEST_PROTOCOL)
        return positive_dict
    



# use bm25 to get top-5 hard-negative document for each did
def create_hard_negatives_data(same_words_dict, positive_dict, json_path, bm25_topk=150):
    json_data = load_data_json(json_path)

    corpus_ids = [d['did'] for d in json_data]
    corpus = []
    titles = []
    title_and_corpus = []

    from zhon.hanzi import punctuation
    import string
    for i, d in enumerate(json_data):
        text_words = d['replaced_text_sentence'].split()
        title_words = d['replaced_title_sentence'].split()

        filter_title_words = [w for w in title_words if w not in punctuation and w not in string.punctuation]
 
        filter_text_words = [w for w in text_words if w not in punctuation and w not in string.punctuation]

        corpus.append(filter_text_words)
        titles.append(filter_title_words)
        title_and_corpus.append(filter_title_words + filter_text_words)
    
    from gensim.summarization import bm25
    print('start build bm25 model...')

    print(len(title_and_corpus))
    # bm25Model = bm25.BM25(corpus)
    bm25Model = bm25.BM25(title_and_corpus)

    for i, query in enumerate(tqdm(titles)):
        q_did = corpus_ids[i]

        if q_did not in positive_dict:
            positive_dict[q_did] = []

 

        scores = bm25Model.get_scores(query)
        best_docs = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:bm25_topk]
        hard_negative_dids = []

        bm25_pos_dids = [corpus_ids[idx] for idx in best_docs]
        pos_dids = positive_dict[q_did]
        pos_dids_set = set(pos_dids)
        hard_negative_dids = [did for did in bm25_pos_dids if did not in pos_dids_set and did != q_did]


        json_data[i]['pos_dids'] = pos_dids
        json_data[i]['hard_neg_dids'] = hard_negative_dids
        json_data[i]['bm25_pos_dids'] = [did for did in bm25_pos_dids if did != q_did]

    json_data = sorted(json_data, key=lambda d: int(d['did'])) 

    with open(json_path, 'w', encoding='utf8') as f:
	    json.dump(json_data, f, ensure_ascii=False)


def tokenize(same_words_dict, json_data, documents_sentence_list_path, titles_sentence_list_path):


    # documents = [d['title'] + ' ' + d['text'] for d in json_data]
    titles = [d['title'] for d in json_data]
    documents = [d['text'] for d in json_data]

    from ckiptagger import data_utils, construct_dictionary, WS, POS, NER
    word_to_weight = {}
    for k, v in same_words_dict.items():
        word_to_weight[k] = 1
        word_to_weight[v] = 1
    dictionary = construct_dictionary(word_to_weight)
    ws = WS("./ckiptagger/data")
    pos = POS("./ckiptagger/data")
    ner = NER("./ckiptagger/data")

    titles_sentence_list = ws(
        titles,
    # sentence_segmentation = True, # To consider delimiters
    # segment_delimiter_set = {",", "。", ":", "?", "!", ";"}), # This is the defualt set of delimiters
    # recommend_dictionary = dictionary, # words in this dictionary are encouraged
    coerce_dictionary = dictionary, # words in this dictionary are forced
    )

    documents_sentence_list = ws(
        documents,
    # sentence_segmentation = True, # To consider delimiters
    # segment_delimiter_set = {",", "。", ":", "?", "!", ";"}), # This is the defualt set of delimiters
    # recommend_dictionary = dictionary, # words in this dictionary are encouraged
    coerce_dictionary = dictionary, # words in this dictionary are forced
    )

    with open(documents_sentence_list_path, 'wb') as handle:
        pickle.dump(documents_sentence_list, handle, protocol=pickle.HIGHEST_PROTOCOL)

    with open(titles_sentence_list_path, 'wb') as handle:
        pickle.dump(titles_sentence_list, handle, protocol=pickle.HIGHEST_PROTOCOL)

    # with open('./data/train_word_sentence_list', 'wb') as handle:
    #     pickle.dump(word_sentence_list, handle, protocol=pickle.HIGHEST_PROTOCOL)


def add_tokenize_word_to_json(documents_sentence_list_path, titles_sentence_list_path, json_path, same_words_dict):

    # with open(word_sentence_list_path, 'rb') as handle:
    #     word_sentence_list = pickle.load(handle)


    with open(documents_sentence_list_path, 'rb') as handle:
        documents_sentence_list = pickle.load(handle)

    with open(titles_sentence_list_path, 'rb') as handle:
        titles_sentence_list = pickle.load(handle)

    json_data = load_data_json(json_path)

    for i , d in enumerate(json_data):
        title_sentence = titles_sentence_list[i]
        text_sentence = documents_sentence_list[i]
        json_data[i]['title_sentence'] = ' '.join(title_sentence)
        json_data[i]['text_sentence'] = ' '.join(text_sentence)

        replaced_title_words = []
        for word in title_sentence:
            for key in same_words_dict.keys():
                if word == key:
                    word = same_words_dict[key]
                    break
                # word = word.replace(key, same_words_dict[key])
            replaced_title_words.append(word)

        replaced_text_words = []
        for word in text_sentence:
            for key in same_words_dict.keys():
                if word == key:
                    word = same_words_dict[key]
                    break
                # word = word.replace(key, same_words_dict[key])
            replaced_text_words.append(word)

        json_data[i]['replaced_title_sentence'] = ' '.join(replaced_title_words)
        json_data[i]['replaced_text_sentence'] = ' '.join(replaced_text_words)
    
    json_data = sorted(json_data, key=lambda d: int(d['did'])) 

    with open(json_path, 'w', encoding='utf8') as f:
	    json.dump(json_data, f, ensure_ascii=False)


def load_data_json(json_path):
    f = open(json_path, 'r')
    json_data = json.load(f)
    f.close()
    return json_data



if __name__ == '__main__':

    mode = 'train'
    folder_path = f'./data/dataTrainComplete/'
    json_path = f'./data/{mode}_complete.json'

    create_train_json(json_path, folder_path)
    json_data = load_data_json(json_path)
    print(len(json_data))

    same_words_dict = create_same_words_dict()
    

    documents_sentence_list_path = f'./data/documents_sentence_list_{mode}'
    titles_sentence_list_path = f'./data/titles_sentence_list_{mode}'
    
    # tokenize(same_words_dict, json_data, documents_sentence_list_path, titles_sentence_list_path)


    add_tokenize_word_to_json(documents_sentence_list_path, titles_sentence_list_path, json_path, same_words_dict)


    # # bm25 create negative sample
    # positive_dict = {}
    positive_dict = create_positive_dict()
    create_hard_negatives_data(same_words_dict, positive_dict, json_path, 200)

    

    # pos_count = 0
    # neg_count = 0
    # avg_text_length = 0
    # avg_title_length = 0
    # for d in json_data:
    #     neg_dids = d['hard_neg_dids']
    #     pos_dids = d['pos_dids']
    #     pos_count += len(pos_dids)
    #     neg_count += len(neg_dids)
    #     text = ''.join(d['replaced_text_sentence'].split())
    #     title = ''.join(d['replaced_title_sentence'].split())
    #     avg_text_length += len(text)
    #     avg_title_length += len(title)


    # print(pos_count / len(json_data))
    # print(neg_count / len(json_data))
    # print(avg_text_length / len(json_data))
    # print(avg_title_length / len(json_data))







    


    

    


