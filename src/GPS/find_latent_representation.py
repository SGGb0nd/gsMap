import logging
import os
import pprint
import random
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import scanpy as sc
from sklearn import preprocessing

from GPS.GNN_VAE.adjacency_matrix import Construct_Adjacency_Matrix
from GPS.GNN_VAE.train import Model_Train

random.seed(20230609)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '[{asctime}] {levelname:8s} {filename} {message}', style='{'))
logger.addHandler(handler)

@dataclass
class FindLatentRepresentationsConfig:
    input_hdf5_path: str
    output_hdf5_path: str
    sample_name: str
    annotation: str = None
    type: str = None

    epochs: int = 300
    feat_hidden1: int = 256
    feat_hidden2: int = 128
    feat_cell: int = 3000
    gcn_hidden1: int = 64
    gcn_hidden2: int = 30
    p_drop: float = 0.1
    gcn_lr: float = 0.001
    gcn_decay: float = 0.01
    n_neighbors: int = 11
    label_w: float = 1
    rec_w: float = 1
    input_pca: bool = True
    n_comps: int = 300
    weighted_adj: bool = False
    nheads: int = 3
    var: bool = False
    convergence_threshold: float = 1e-4
    hierarchically: bool = False


# Set args
import argparse
def add_find_latent_representations_args(parser):

    parser.add_argument('--epochs', default=300, type=int, help="Number of training epochs for the GNN-VAE model. Default is 300.")
    parser.add_argument('--feat_hidden1', default=256, type=int, help="Number of neurons in the first hidden layer of the feature extraction network. Default is 256.")
    parser.add_argument('--feat_hidden2', default=128, type=int, help="Number of neurons in the second hidden layer of the feature extraction network. Default is 128.")
    parser.add_argument('--feat_cell', default=3000, type=int, help="Number of top variable genes to select. Default is 3000.")
    parser.add_argument('--gcn_hidden1', default=64, type=int, help="Number of units in the first hidden layer of the GCN. Default is 64.")
    parser.add_argument('--gcn_hidden2', default=30, type=int, help="Number of units in the second hidden layer of the GCN. Default is 30.")
    parser.add_argument('--p_drop', default=0.1, type=float, help="Dropout rate used in the GNN-VAE model. Default is 0.1.")
    parser.add_argument('--gcn_lr', default=0.001, type=float, help="Learning rate for the GCN network. Default is 0.001.")
    parser.add_argument('--gcn_decay', default=0.01, type=float, help="Weight decay (L2 penalty) for the GCN network. Default is 0.01.")
    parser.add_argument('--n_neighbors', default=11, type=int, help="Number of neighbors to consider for graph construction in GCN. Default is 11.")
    parser.add_argument('--label_w', default=1, type=float, help="Weight of the label loss in the loss function. Default is 1.")
    parser.add_argument('--rec_w', default=1, type=float, help="Weight of the reconstruction loss in the loss function. Default is 1.")
    parser.add_argument('--input_pca', default=True, type=bool, help="Whether to perform PCA on input features. Default is True.")
    parser.add_argument('--n_comps', default=300, type=int, help="Number of principal components to keep if PCA is performed. Default is 300.")
    parser.add_argument('--weighted_adj', default=False, type=bool, help="Whether to use a weighted adjacency matrix in GCN. Default is False.")
    parser.add_argument('--nheads', default=3, type=int, help="Number of heads in the attention mechanism of the GNN. Default is 3.")
    parser.add_argument('--var', default=False, type=bool)
    parser.add_argument('--convergence_threshold', default=1e-4, type=float, help="Threshold for convergence during training. Training stops if the loss change is below this threshold. Default is 1e-4.")
    parser.add_argument('--hierarchically', default=False, type=bool, help="Whether to find latent representations hierarchically. Default is False.")

    parser.add_argument('--input_hdf5_path', required=True, type=str, help='Path to the input hdf5 file.')
    parser.add_argument('--output_hdf5_path', required=True, type=str, help='Path to the output hdf5 file.')
    parser.add_argument('--sample_name', required=True, type=str, help='Name of the sample.')
    parser.add_argument('--annotation', default=None, type=str, help='Name of the annotation layer.')
    parser.add_argument('--type', default=None, type=str, help="Type of input data (e.g., 'count', 'counts').")




# The class for finding latent representations
class Latent_Representation_Finder:

    def __init__(self, adata, Params):
        self.adata = adata.copy()
        self.Params = Params

        # Standard process
        if self.Params.type == 'count' or self.Params.type == 'counts':
            self.adata.X = self.adata.layers[self.Params.type]
            sc.pp.highly_variable_genes(self.adata, flavor="seurat_v3", n_top_genes=self.Params.feat_cell)
            sc.pp.normalize_total(self.adata, target_sum=1e4)
            sc.pp.log1p(self.adata)
            sc.pp.scale(self.adata)
        else:
            self.adata.X = self.adata.layers[self.Params.type]
            sc.pp.highly_variable_genes(self.adata, n_top_genes=self.Params.feat_cell)

    def Run_GNN_VAE(self, label, verbose='whole ST data'):

        # Construct the neighbouring graph
        graph_dict = Construct_Adjacency_Matrix(self.adata, self.Params)

        # Process the feature matrix
        node_X = self.adata[:, self.adata.var.highly_variable].X
        print(f'The shape of feature matrix is {node_X.shape}.')
        if self.Params.input_pca:
            node_X = sc.pp.pca(node_X, n_comps=self.Params.n_comps)

        # Update the input shape
        self.Params.n_nodes = node_X.shape[0]
        self.Params.feat_cell = node_X.shape[1]

        # Run GNN-VAE
        print(f'------Finding latent representations for {verbose}...')
        gvae = Model_Train(node_X, graph_dict, self.Params, label)
        gvae.run_train()

        return gvae.get_latent()

    def Run_PCA(self):
        sc.tl.pca(self.adata)
        return self.adata.obsm['X_pca'][:, 0:self.Params.n_comps]


def run_find_latent_representation(args:FindLatentRepresentationsConfig):
    num_features = args.feat_cell
    args.output_dir = Path(args.output_hdf5_path).parent
    args.output_dir.mkdir(parents=True, exist_ok=True,mode=0o755)
    # Load the ST data
    print(f'------Loading ST data of {args.sample_name}...')
    adata = sc.read_h5ad(f'{args.input_hdf5_path}')
    adata.var_names_make_unique()
    print('The ST data contains %d cells, %d genes.' % (adata.shape[0], adata.shape[1]))
    # Load the cell type annotation
    if not args.annotation is None:
        # remove cells without enough annotations
        adata = adata[~pd.isnull(adata.obs[args.annotation]), :]
        num = adata.obs[args.annotation].value_counts()
        adata = adata[adata.obs[args.annotation].isin(num[num >= 30].index.to_list()),]

        le = preprocessing.LabelEncoder()
        le.fit(adata.obs[args.annotation])
        adata.obs['categorical_label'] = le.transform(adata.obs[args.annotation])
        label = adata.obs['categorical_label'].to_list()
    else:
        label = None
    # Find latent representations
    latent_rep = Latent_Representation_Finder(adata, args)
    latent_GVAE = latent_rep.Run_GNN_VAE(label)
    latent_PCA = latent_rep.Run_PCA()
    # Add latent representations to the spe data
    print(f'------Adding latent representations...')
    adata.obsm["latent_GVAE"] = latent_GVAE
    adata.obsm["latent_PCA"] = latent_PCA
    # Run umap based on latent representations
    for name in ['latent_GVAE', 'latent_PCA']:
        sc.pp.neighbors(adata, n_neighbors=10, use_rep=name)
        sc.tl.umap(adata)
        adata.obsm['X_umap_' + name] = adata.obsm['X_umap']

        # TODO : Don't know the meaning of the following code
        # Find the latent representations hierarchically (optionally)
    if not args.annotation is None and args.hierarchically:
        print(f'------Finding latent representations hierarchically...')
        PCA_all = pd.DataFrame()
        GVAE_all = pd.DataFrame()

        for ct in adata.obs[args.annotation].unique():
            adata_part = adata[adata.obs[args.annotation] == ct, :]
            print(adata_part.shape)

            # Find latent representations for the selected ct
            latent_rep = Latent_Representation_Finder(adata_part, args)

            latent_PCA_part = pd.DataFrame(latent_rep.Run_PCA())
            if adata_part.shape[0] <= args.n_comps:
                latent_GVAE_part = latent_PCA_part
            else:
                latent_GVAE_part = pd.DataFrame(latent_rep.Run_GNN_VAE(label=None, verbose=ct))

            latent_GVAE_part.index = adata_part.obs_names
            latent_PCA_part.index = adata_part.obs_names

            GVAE_all = pd.concat((GVAE_all, latent_GVAE_part), axis=0)
            PCA_all = pd.concat((PCA_all, latent_PCA_part), axis=0)

            args.feat_cell = num_features

            adata.obsm["latent_GVAE_hierarchy"] = np.array(GVAE_all.loc[adata.obs_names,])
            adata.obsm["latent_PCA_hierarchy"] = np.array(PCA_all.loc[adata.obs_names,])
    print(f'------Saving ST data...')
    adata.write(args.output_hdf5_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="This script is designed to find latent representations in spatial transcriptomics data using a Graph Neural Network Variational Autoencoder (GNN-VAE). It processes input data, constructs a neighboring graph, and runs GNN-VAE to output latent representations.")
    add_find_latent_representations_args(parser)
    TEST=True
    if TEST:
        test_dir = '/storage/yangjianLab/chenwenhao/projects/202312_GPS/data/GPS_test/Nature_Neuroscience_2021'
        name = 'Cortex_151507'


        args = parser.parse_args(
            [
                '--input_hdf5_path','/storage/yangjianLab/songliyang/SpatialData/Data/Brain/Human/Nature_Neuroscience_2021/processed/h5ad/Cortex_151507.h5ad',
                '--output_hdf5_path',f'{test_dir}/{name}/hdf5/{name}_add_latent.h5ad',
                '--sample_name', name,
                '--annotation','layer_guess',
                '--type','count',
            ]

        )

    else:
        args = parser.parse_args()
    config=FindLatentRepresentationsConfig(**vars(args))
    start_time = time.time()
    logger.info(f'Find latent representations for {config.sample_name}...')
    pprint.pprint(config)
    run_find_latent_representation(config)
    end_time = time.time()
    logger.info(f'Find latent representations for {config.sample_name} finished. Time spent: {(end_time - start_time) / 60:.2f} min.')