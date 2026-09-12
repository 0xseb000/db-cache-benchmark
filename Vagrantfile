# Three-VM lab for the cache-aside benchmark.
#
#   pg     PostgreSQL, holds the data
#   redis  Redis, caches the report the web app asks for
#   web    the web application the browser talks to
#
# The chain is pg -> redis -> web: the browser only ever sees the web VM, the
# web VM asks Redis first and only falls back to PostgreSQL on a cache miss.

BOX = "bento/debian-12"

NODES = [
  { name: "pg",    ip: "192.168.56.10", memory: 2048, cpus: 2 },
  { name: "redis", ip: "192.168.56.11", memory: 1024, cpus: 1 },
  { name: "web",   ip: "192.168.56.12", memory: 1024, cpus: 1 },
]

Vagrant.configure("2") do |config|
  config.vm.box = BOX

  NODES.each_with_index do |node, index|
    last = index == NODES.length - 1

    config.vm.define node[:name], primary: last do |machine|
      machine.vm.hostname = node[:name]
      machine.vm.network "private_network", ip: node[:ip]

      machine.vm.provider "parallels" do |prl|
        prl.name               = "cache-#{node[:name]}"
        prl.memory             = node[:memory]
        prl.cpus               = node[:cpus]
        prl.update_guest_tools = false
      end

      # Ansible runs once, on the last machine to come up, against the whole
      # inventory. One run configures all three VMs in dependency order.
      next unless last

      machine.vm.provision "ansible" do |ansible|
        ansible.playbook = "ansible/site.yml"
        ansible.limit    = "all"
      end
    end
  end
end
