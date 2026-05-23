import paramiko
import os

SSH_HOST = '47.251.102.205'
SSH_USER = 'root'
SSH_PASSWORD = 'dingyuchenA1@'

pub_key_path = os.path.expanduser('~/.ssh/id_rsa.pub')
with open(pub_key_path, 'r') as f:
    pub_key = f.read().strip()

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(SSH_HOST, port=22, username=SSH_USER, password=SSH_PASSWORD, timeout=15)

stdin, stdout, stderr = client.exec_command('mkdir -p ~/.ssh && chmod 700 ~/.ssh')
stdout.read()

cmd = f'echo "{pub_key}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys'
stdin, stdout, stderr = client.exec_command(cmd)
out = stdout.read().decode()
err = stderr.read().decode()

client.close()

if err:
    print(f'Error: {err}')
else:
    print('SSH key deployed successfully!')
    print('Now you can SSH without password')
