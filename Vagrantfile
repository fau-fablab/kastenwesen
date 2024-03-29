# -*- mode: ruby -*-
# vi: set ft=ruby :

# Vagrantfile API/syntax version. Don't touch unless you know what you're doing!
VAGRANTFILE_API_VERSION = "2"

Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|
  # All Vagrant configuration is done here. The most common configuration
  # options are documented and commented below. For a complete reference,
  # please see the online documentation at vagrantup.com.

  # Every Vagrant virtual environment requires a box to build off of.
  config.vm.box = "ubuntu/jammy64"

  # Disable automatic box update checking. If you disable this, then
  # boxes will only be checked for updates when the user runs
  # `vagrant box outdated`. This is not recommended.
  # config.vm.box_check_update = false

  # Create a forwarded port mapping which allows access to a specific port
  # within the machine from a port on the host machine. In the example below,
  # accessing "localhost:8080" will access port 80 on the guest machine.
  # config.vm.network "forwarded_port", guest: 80, host: 8080

  # Create a private network, which allows host-only access to the machine
  # using a specific IP.
  # TODO
  config.vm.hostname = "vagrant-docker-host-vm"
  # config.vm.network "private_network", ip: "192.168.33.10"

  # Create a public network, which generally matched to bridged network.
  # Bridged networks make the machine appear as another physical device on
  # your network.
  # config.vm.network "public_network"

  # If true, then any SSH connections made will enable agent forwarding.
  # Default value: false
  # config.ssh.forward_agent = true

  # Share an additional folder to the guest VM. The first argument is
  # the path on the host to the actual folder. The second argument is
  # the path on the guest to mount the folder. And the optional third
  # argument is a set of non-required options.
  
  # ATTENTION, this setting shares the whole git repo with the VM and therefore does not provide separation between host and VM.
  # (the VM may edit git-hooks in .git that git on the host can execute)
  config.vm.synced_folder ".", "/home/vagrant/share", disabled: false

  # Provider-specific configuration so you can fine-tune various
  # backing providers for Vagrant. These expose provider-specific options.
  # Example for VirtualBox:
  #
   config.vm.provider "virtualbox" do |vb|
  #   # GUI or headless mode?
     vb.gui = false
  #
  #   # Use VBoxManage to customize the VM. For example to change memory:
  #   vb.customize ["modifyvm", :id, "--memory", "1024"]
   end
  #
  # View the documentation for the provider you're using for more
  # information on available options.

  
  config.vm.provision "shell" do |foobar|
    foobar.inline = "cd /home/vagrant/share/ && ./install_ubuntu.sh"
  end
  config.vm.provision "shell" do |foobar|
    foobar.inline = "ln -fs /home/vagrant/share/example-config /etc/kastenwesen"
  end
  config.vm.provision "shell" do |foobar|
    foobar.inline = "ln -fs /home/vagrant/share/example-config /home/vagrant/kastenwesen-config"
  end
  config.vm.provision "shell" do |foobar|
    foobar.inline = "ln -fs /home/vagrant/share/kastenwesen.py /usr/bin/kastenwesen"
  end
end
