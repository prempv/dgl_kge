from models import KEModel

import mxnet as mx
from mxnet import gluon
from mxnet import ndarray as nd

import os
import logging
import time
import json

def load_model(logger, args, n_entities, n_relations, ckpt=None):
    model = KEModel(args, args.model_name, n_entities, n_relations,
                    args.hidden_dim, args.gamma,
                    double_entity_emb=args.double_ent, double_relation_emb=args.double_rel)
    if ckpt is not None:
        assert False, "We do not support loading model emb for genernal Embedding"

    logger.info('Load model {}'.format(args.model_name))
    return model

def load_model_from_checkpoint(logger, args, n_entities, n_relations, ckpt_path):
    model = load_model(logger, args, n_entities, n_relations)
    model.load_emb(ckpt_path, args.dataset)
    return model

def train(args, model, train_sampler, rank=0, rel_parts=None, valid_samplers=None):
    assert args.num_proc == 1, "MXNet KGE does not support multi-process now"
    assert args.rel_part == False, "No need for relation partition in single process for MXNet KGE"
    logs = []

    for arg in vars(args):
        logging.info('{:20}:{}'.format(arg, getattr(args, arg)))

    if len(args.gpu) > 0:
        gpu_id = args.gpu[rank % len(args.gpu)] if args.mix_cpu_gpu and args.num_proc > 1 else args.gpu[0]
    else:
        gpu_id = -1

    start = time.time()
    for step in range(args.init_step, args.max_step):
        pos_g, neg_g = next(train_sampler)
        args.step = step
        with mx.autograd.record():
            loss, log = model.forward(pos_g, neg_g, gpu_id)
        loss.backward()
        logs.append(log)
        model.update(gpu_id)

        if step % args.log_interval == 0:
            for k in logs[0].keys():
                v = sum(l[k] for l in logs) / len(logs)
                print('[Train]({}/{}) average {}: {}'.format(step, args.max_step, k, v))
            logs = []
            print(time.time() - start)
            start = time.time()

        if args.valid and step % args.eval_interval == 0 and step > 1 and valid_samplers is not None:
            start = time.time()
            test(args, model, valid_samplers, mode='Valid')
            print('test:', time.time() - start)
    # clear cache
    logs = []

def test(args, model, test_samplers, rank=0, mode='Test', queue=None):
    assert args.num_proc == 1, "MXNet KGE does not support multi-process now"
    logs = []

    if len(args.gpu) > 0:
        gpu_id = args.gpu[rank % len(args.gpu)] if args.mix_cpu_gpu and args.num_proc > 1 else args.gpu[0]
    else:
        gpu_id = -1

    for sampler in test_samplers:
        #print('Number of tests: ' + len(sampler))
        count = 0
        for pos_g, neg_g in sampler:
            model.forward_test(pos_g, neg_g, logs, gpu_id)

    metrics = {}
    if len(logs) > 0:
        for metric in logs[0].keys():
            metrics[metric] = sum([log[metric] for log in logs]) / len(logs)

    for k, v in metrics.items():
        print('{} average {} at [{}/{}]: {}'.format(mode, k, args.step, args.max_step, v))
    for i in range(len(test_samplers)):
        test_samplers[i] = test_samplers[i].reset()
