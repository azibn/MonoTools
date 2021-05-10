from setuptools import setup
import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name='MonoTools',
    version='0.1.3',
    description='A package for detecting, vetting and modelling transiting exoplanets on uncertain periods',
    url='https://github.com/hposborn/MonoTools',
    author='Hugh P. Osborn',
    author_email='hugh.osborn@space.unibe.ch',
    long_description=long_description,
    long_description_content_type="text/markdown",
    license='BSD 2-clause',
    project_urls={
        "Bug Tracker": "https://github.com/hposborn/MonoTools/issues",
    },
    packages=setuptools.find_packages(),
    package_data={'MonoTools': extrafiles},
    install_requires=['matplotlib',
                      'numpy',
                      'pandas',
                      'scipy',
                      'astropy',
                      'astroquery',
                      'batman-package==2.4.7',
                      'lightkurve==1.11.0',
                      'arviz==0.11',
                      'Theano==1.0.4',
                      'pymc3==3.8',
                      'exoplanet==0.3.2',
                      'celerite',
                      'requests',
                      'urllib3',
                      'lxml',
                      'httplib2',
                      'h5py',
                      'ipython',
                      'bokeh',
                      'corner',
                      'transitleastsquares',
                      'eleanor',
                      'seaborn',
                      'iteround',
                      ],
    classifiers=[
        'Development Status :: 1 - Planning',
        'Intended Audience :: Science/Research',
    ],
)
