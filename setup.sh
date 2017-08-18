
sudo apt update
sudo apt install python-setuptools python3 python3-pip mongodb libcurl4-openssl-dev libssl-dev dialog jq curl python-pyaes build-essential
sudo curl -sL https://deb.nodesource.com/setup_8.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo dpkg --configure -a
sudo apt install -f
sudo pip3 install pycurl
sudo pip3 install pyyaml
sudo pip3 install pyparse
sudo pip3 install parse
sudo pip3 install pyaes
sudo pip3 install pandas
sudo pip3 install pymongo
sudo python3 setup.py install
sudo npm install
sudo npm link

echo "Input your poloniex (preferred) Key and hash into conf-example.js"
echo "...And Then... sudo python3 macdtrader.py... the database will fill on each round... this takes awhile... but the database will fill eventually and the program should become faster... Happy trading!"
