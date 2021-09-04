#!/usr/bin/env python3
'''
Scan the file system to build a JSON simulations manifest for the data portal.

In detail, builds two manifests: one for the website/table that groups small
sims into sets of 100, and one exploded manifest for the backend.

Usage
-----
$ ./build_manifest.py --help
'''

import json
import argparse
from pathlib import Path
import os
import copy
import re
from collections import defaultdict

from tqdm import tqdm
# These are needed to read the header
import abacusnbody.data.asdf
import asdf

# omissions:
# ICs don't quite fall in the redshift-product-ftype hierarchy
# MergerTest doesn't have the standard set of redshifts

#DEFAULT_ROOT = '/mnt/ceph/users/lgarrison/AbacusSummit'
DEFAULT_ROOT = os.environ['CFS'] + '/desi/cosmosim/Abacus'
DEFAULT_PRODUCTS = dict(halos=dict(path='{}/halos', ftypes=('halo_info','halo_rv_A','halo_pid_A','field_rv_A','field_pid_A')),
                        cleaning=dict(path='cleaning/{}', ftypes=('cleaned_halo_info','cleaned_rvpid')),
                        power=dict(path='power/{}', ftypes=('AB','pack9')),
                        )
                        #lightcones=('heal','pid','rv')  # TODO
DEFAULT_SIM_PATS = ('AbacusSummit_*/', 'small/AbacusSummit_*/')
DEFAULT_OUTDIR = 'web/portal/static/data/'

DEFAULT_REDSHIFTS = [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.575, 0.65, 0.725, 0.8, 0.875, 0.95, 1.025, 1.1, 1.175, 1.25, 1.325, 1.4, 1.475, 1.55, 1.625, 1.7, 1.85, 2.0, 2.25, 2.5, 2.75, 3.0, 5.0, 8.0]

def find_products(simdir, products, redshifts):
    parent, child = simdir
    j = {}
    header = {}
    for prod in products:
        j[prod] = {}  # j['halos']
        pdir = parent / products[prod]['path'].format(child)
        for zdir in sorted(pdir.glob('z*/')):
            zval = zdir.name[1:]
            zval = float(zval)
            assert zval in DEFAULT_REDSHIFTS
            if zval not in redshifts:
                continue
            j[prod][zval] = {}  # j['halos']['0.100']
            for ftype in products[prod]['ftypes']:
                if (fpath:=zdir/ftype).is_dir():
                    du = [fn.stat().st_size for fn in fpath.iterdir()]
                    nfile = len(du)
                    du = sum(du)
                    j[prod][zval][ftype] = [nfile,du]  # j['halos']['0.100']['halo_info']

                    if not header:
                        try:
                            with asdf.open(next(fpath.glob('*.asdf'))) as af:
                                for k in ('BoxSize','SimComment','ParticleMassHMsun'):
                                    header[k] = af['header'][k]

                                header['PPD'] = int(round(af['header']['NP']**(1/3)))
                        except Exception as e:
                            raise Exception(f'Failed in: {fpath}') from e
                            
            # this z not on disk?
            if not j[prod][zval]:
                del j[prod][zval]
        # no halos?
        if not j[prod]:
            del j[prod]
    # no products?
    if not j:
        return None
    
    j['header'] = header
    return j


def _collapsed_manifest(manifest, ngroup=100, nsingle=10):
    '''Group the small sims in sets of 100.
    '''
    manifest = copy.deepcopy(manifest)
    rows = manifest['data']
    
    newrows = {}
    
    for row in rows:
        row['all_ids'] = [row['id']]
    
    grouprows = {}
    for row in rows:
        if m:=re.match(r'AbacusSummit_small_c\d{3}_ph(\d{4})', row['name']):
            # Preserve a few small sims for individual download
            if nsingle:
                newrows[row['name']] = copy.deepcopy(row)
                nsingle -= 1
            ph = int(m.group(1))
            baseph = ph//ngroup*ngroup
            groupname = row['name'][:-4] + f'{{{baseph}-{baseph+ngroup-1}}}'
            if groupname not in grouprows:
                grouprow = copy.deepcopy(row)
                del grouprow['root']
                grouprows[groupname] = grouprow
                grouprow['name'] = groupname
                grouprow['all_ids'] = []  # start a list of all ids in this set
                grouprow['header']['SimComment'] = 'Set of 100 small boxes, base cosmology, no lightcone'
            else:
                grouprow = grouprows[groupname]
                # Add du, if not copied
                for p in manifest['products']:
                    if p not in row:
                        continue
                    for z in row[p]:
                        if z not in grouprow[p]:
                            grouprow[p][z] = copy.deepcopy(row[p][z])  # init if necessary
                            continue
                        for ftype in row[p][z]:
                            grouprow[p][z][ftype][0] += row[p][z][ftype][0]
                            grouprow[p][z][ftype][1] += row[p][z][ftype][1]
                            
            grouprow['all_ids'] += [row['id']]
            
        else:
            newrows[row['name']] = row
            
    newrows.update(grouprows)
            
    # fix IDs
    newrows = list(newrows.values())
    for uid,row in enumerate(newrows):
        row['id'] = uid
    manifest['data'] = newrows
    
    return manifest


#def _round_floats(manifest):
#    rows = manifest['data']
#    for p in manifest['products']:
#        if p not in row:
#            continue
#        for z in row[p]:
#            for ftype in row[p][z]:
#                row[p][z][ftype][1] = f'{row[p][z][ftype][1]:.3g}'
    

def main(sim_pats=DEFAULT_SIM_PATS,
         products=DEFAULT_PRODUCTS,
         root=DEFAULT_ROOT,
         out=DEFAULT_OUTDIR,
         redshifts=DEFAULT_REDSHIFTS,
         compact=False,
        ):
    root = Path(root)
    out = Path(out)
    
    sims = []
    for pat in sim_pats:
        sims += root.glob(pat)
    
    rows = []  # d['AbacusSummit_base_c000_ph000']['halos']['z0.100']['halo_info']
    
    #sims = [sim for i,sim in enumerate(sorted(sims)) if i == 0 or i > 2050]
    for sim in tqdm(sorted(sims)):
        sim = Path(sim)
        slug = str(sim.relative_to(root))
        
        row = find_products((root, slug), products, redshifts)
        if row:
            row.update({'name': sim.name,
                        'root': slug,
                        })
            rows += [row]
    
    # add the index to each row
    for uid,row in enumerate(rows):
        row['id'] = uid
            
    # figure out which z we actually have any data for
    redshifts = list(sorted(set(sum((sum( (list(row.get(prod,[])) for row in rows),[]) for prod in products),[] ))))
    print(len(redshifts), redshifts)
    
    manifest = {'data':rows,
                'redshifts':redshifts,
                # TODO
                'products':products}
    
    # Collapse any groups of sims
    collapsed_manifest = _collapsed_manifest(manifest)
    
    if compact:
        jsargs = dict(separators=(',', ':'))
    else:
        jsargs = dict(indent=4)
    s = json.dumps(manifest, indent=4)
    #print(s)
    with open(out / "simulations.json", 'w', encoding='utf-8') as fp:
        fp.write(s)
    with open(out / "simulations.table.json", 'w', encoding='utf-8') as fp:
        json.dump(collapsed_manifest, fp, **jsargs)


class ArgParseFormatter(argparse.RawDescriptionHelpFormatter,
                        argparse.ArgumentDefaultsHelpFormatter):
    pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=ArgParseFormatter)
    #parser.add_argument('sims', help='Simulation', nargs='+', metavar='SIM')
    parser.add_argument('-o','--out', help='Output dir for JSON', default=DEFAULT_OUTDIR)

    args = parser.parse_args()
    args = vars(args)

    main(**args)
