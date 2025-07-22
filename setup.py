from setuptools import setup

setup(
    name = 'cassette_store',
    description = 'Tools to save/load cassette-tape audio data',
    version = '1.0',
    author = 'Jan Wieck',
    author_email = 'jan@wi3ck.info',
    url = None,
    license = 'MIT',
    packages = ['cassette_store'],
    entry_points = {
        'console_scripts': [
            'cstore = cassette_store.cstore_cmd:main',
        ]
    }
)
