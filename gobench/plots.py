#!/usr/bin/env python
# Copyright (c) 2018 Sylvain Gubian <sylvain.gubian@pmi.com>,
# Yang Xiang <yang.xiang@pmi.com>
# Author: Sylvain Gubian, PMP S.A.
# -*- coding: utf-8 -*-
import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import scipy.cluster.hierarchy as sch
import fastcluster

def get_data_info(data, info='nbruns'):
    methods = list(data.keys())
    fnames = list(data[methods[0]].keys())
    metrics = list(data[methods[0]][fnames[0]].keys())
    nbruns = len(data[methods[0]][fnames[0]][metrics[0]])
    if info == 'fnames':
        return fnames
    elif info == 'methods':
        return methods
    elif info == 'metrics':
        return metrics
    else:
        return nbruns

def all_func_nb_call(data):
    # Plotting for all functions
    d = {}
    fnames = []
    nb_runs = get_data_info(data)
    for k in data:
        d[k] = np.empty([nb_runs, len(data[k])])
        for i, f in enumerate(data[k]):
            d[k][:, i] = data[k][f]['ncall']
            if f not in fnames:
                fnames.append(f)
        df = pd.DataFrame(d[k], columns=fnames)
        axes = df.plot.box(title=k)
        axes.set_ylim([0, 10000])
        axes.set_xticklabels(
                axes.xaxis.get_majorticklabels(),
                rotation=90
                )
        plt.show(k)

def barplot(data, file_path):
    file_format = os.path.splitext(file_path)[1]
    if file_format not in ['.svg', '.pdf', '.png', '.eps']:
        raise ValueError('Invalid file format extention')
    doa = {}
    nb_runs = get_data_info(data)
    for k in data:
        doa[k] = []
        for i, f in enumerate(data[k]):
            values = data[k][f]['ncall']
            success = np.sum(
                data[k][f]['success']) * 100 / nb_runs
            if np.isnan(success):
                success = 0
            # Normalizing values
            values /= np.max(np.abs(values), axis=0)
            if i == 0:
                doa[k][:] = values
            else:
                doa[k] = np.append(doa[k], values)
    df = pd.DataFrame(doa, columns=data.keys())
    #axes = df.plot.box(notch=False, title='Normalized Overall function calls')
    axes = df.plot.bar(title='Normalized Overall function calls')
    axes.set_ylim([-0.5, 1.1])
    # ax = axes.set_xticklabels(axes.xaxis.get_majorticklabels(), rotation=90)
    plt.savefig(file_path, bbox_inches='tight', format=file_format[1:])

def heatmap_reliability(data, file_path):
    file_format = os.path.splitext(file_path)[1]
    if file_format not in ['.svg', '.pdf', '.png', '.eps']:
        raise ValueError('Invalid file format extention')
    nb_runs = get_data_info(data)
    nb_func = len(get_data_info(data, 'fnames'))
    methods = get_data_info(data, 'methods')
    mat = np.empty([nb_func, len(methods)])
    for j, k in enumerate(data):
        for i, f in enumerate(data[k]):
            success = np.sum(
                data[k][f]['success']) * 100 / nb_runs
            if np.isnan(success):
                success = 0
            mat[i, j] = success
    # mat.sort(axis=0)
    fig = plt.figure()
    ax1 = fig.add_axes([0.7, 0.1, 0.18, 0.8])
    Y = fastcluster.linkage(mat, method='ward')
    Z1 = sch.dendrogram(Y, orientation='right')
    ax1.set_xticks([])
    ax1.set_yticks([])
    axmatrix = fig.add_axes([0.1, 0.1, 0.6, 0.8])
    axmatrix.set_title(('Success rate across tested  functions '
                        '(reliability over {} runs)').format(nb_runs))
    im = axmatrix.matshow(
            mat[Z1['leaves'], :], aspect='auto', origin='lower',
            cmap=plt.cm.RdYlGn,
            )
    methods.insert(0, ' ')
    axmatrix.set_xticklabels(methods)
    # Reorder functions indexes:
    c = np.arange(0, nb_func)[Z1['leaves']]
    axmatrix.set_yticks(np.arange(0, nb_func, 10))
    axmatrix.set_yticklabels(c)
    axmatrix.set_ylabel('Test function number')
    axcolor = fig.add_axes([0.9, 0.1, 0.02, 0.8])
    plt.colorbar(im, cax=axcolor)
    fig.savefig(file_path, bbox_inches='tight', format=file_format[1:])

def main(data_path):
    print('Retrieving data...')
    data = get_data(data_path)
    # overall_fncall(data)
    heat_map_reliability(data)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Path to benchmark data folder has to be provided as arg')
        sys.exit(-1)
    main(sys.argv[1])
