"""Example program to show how to read a multi-channel time series from LSL."""
import time
from torch import nn
import torch
import numpy as np
from pylsl import StreamInlet, resolve_stream
from socket import *
import time
import joblib
from data_preprocess import dataPreprocess


def init_weight(module, non_linear):
    nn.init.kaiming_uniform_(module.weight, nonlinearity=non_linear)
    nn.init.zeros_(module.bias)


class ConvNets_FFT(nn.Module):
    def __init__(self, num_class):
        super().__init__()
        self.module = nn.ModuleDict({
            'conv1': nn.Conv2d(8, 20, [1, 5]),
            'relu1': nn.ReLU(),
            'bn1': nn.BatchNorm2d(20),
            'pool1': nn.MaxPool2d([1, 2]),

            'conv2': nn.Conv2d(20, 40, [1, 3]),
            'bn2': nn.BatchNorm2d(40),
            'tanh1': nn.Tanh(),
            'pool2': nn.MaxPool2d([1, 2]),

            'conv3': nn.Conv2d(40, 60, [1, 3]),
            'relu2': nn.ReLU(),
            'bn3': nn.BatchNorm2d(60),
            'pool3': nn.MaxPool2d([1, 3]),

            'conv4': nn.Conv2d(60, 80, [1, 3], stride=[1, 3]),
            'bn4': nn.BatchNorm2d(80),
            'tanh2': nn.Tanh(),
        })
        self.fft_module = nn.ModuleDict({
            'conv1': nn.Conv2d(8, 16, [1, 5], stride=[1, 2]),
            'relu1': nn.ReLU(),
            'bn1': nn.BatchNorm2d(16),

            'conv2': nn.Conv2d(16, 16, [1, 3], stride=[1, 2]),
            'bn2': nn.BatchNorm2d(16),
            'tanh1': nn.Tanh(),
            'pool1': nn.MaxPool2d([1, 2])
        })
        self.dropout = nn.Dropout(p=0.4)
        self.linear1 = nn.Linear(240, num_class)

        init_weight(self.module['conv1'], 'relu')
        init_weight(self.module['conv2'], 'tanh')
        init_weight(self.module['conv3'], 'relu')
        init_weight(self.module['conv4'], 'tanh')
        init_weight(self.fft_module['conv1'], 'relu')
        init_weight(self.fft_module['conv2'], 'tanh')
        init_weight(self.linear1, 'relu')

    def forward(self, x):
        fft = torch.fft.fft(x, 88).real[:, :, :, 0:45]
        for key in self.module:
            x = self.module[key](x)
        for key in self.fft_module:
            fft = self.fft_module[key](fft)

        x = torch.cat((x.flatten(start_dim=1), fft.flatten(start_dim=1)), dim=1)
        x = self.dropout(x)
        x = self.linear1(x)
        x = torch.nn.functional.softmax(x, dim=1)
        return x


def overlap(data):
    for i in range(2):
        new_data = np.concatenate((data[i][:, 44:], data[i+1][:, :44]), axis=1)
        data.append(new_data)
    return data


def data_normal(data_set):
    length = len(data_set)
    for i in range(length):
        seq = data_set[i]
        a = np.mean(seq)
        D = np.var(seq)
        seq = (seq - a) / np.sqrt(D) # 中心化/标准化
        data_set[i] = seq[None, :, :]
    return data_set


if __name__ == '__main__':
    # print("looking for a stream...")
    # first resolve a Motion stream on the lab network
    streams = resolve_stream('type',
                             'EEG')  # You can try other stream types such as: EEG, EEG-Quality, Contact-Quality, Performance-Metrics, Band-Power
    # print(streams)

    # create a new inlet to read from the stream
    inlet = StreamInlet(streams[0])
    ist1, ist2 = 0, 0
    total_ist = 0
    percent_data = []
    test_data = []

    action2id = {'空': 0, '起飞': 1, '向左': 2, '向右': 3, '降落': 4, '舌动': 5, '眼动': 6}
    id2action = {0: '空', 1: '起飞', 2: '向左', 3: '向右', 4: '降落', 5: '舌动', 6: '眼动'}

    model = joblib.load(filename='E:/desktop/test328/test/CNN_静息眼动.pkl')

    device = "cuda" if torch.cuda.is_available() else "cpu"  # device is cuda

    # 1.创建套接字
    # tcp_socket = socket(AF_INET,SOCK_STREAM)
    # # 2.准备连接服务器，建立连接
    # serve_ip = "192.168.31.211"
    # serve_port = 12220  #端口，比如8000
    # tcp_socket.connect((serve_ip,serve_port))  # 连接服务器，建立连接,参数是元组形式

    # 与matlab的链接↓
    # IPV4,TCP协议
    sock = socket(AF_INET, SOCK_STREAM)
    # 绑定ip和端口，bind接受的是一个元组
    sock.bind(('127.0.0.1', 8000))
    # 设置监听，其值阻塞队列长度，一共可以有5+1个客户端和服务器连接
    sock.listen(5)
    connection,address = sock.accept()
    # 与matlab的链接↑

    # start_time = time.time()
    # 控制数据读取
    save_data = False
    final_ins = 0
    data0 = []
    data1 = []
    onoff = 1
    while True:
        # Returns a tuple (sample,timestamp) where sample is a list of channel values and timestamp is the capture time of the sample on the remote machine,
        # or (None,None) if no new sample was available
        if total_ist % 1280 == 0:   # 每十秒开始读， 只处理前6秒数据（前3秒和后3秒对应不同的脑电信号）， 后4秒给操作者用来缓冲
            save_data = True
        sample, timestamp = inlet.pull_sample()
        total_ist += 1

        if total_ist % 12 == 6:
            data0 = sample[3: 17]
        elif total_ist % 12 == 0:
            data1 = sample[3: 17]
            # 与matlab的链接↓
            data0.append(final_ins)
            data1.append(final_ins)
            aa = data0 + data1  # 加入指令
            s = str(aa)
            buf = connection.recv(40960)
            info = buf.decode('utf-8')
            connection.send(bytes(s, encoding="utf-8"))
            if 'switch' in info:
                print('switch=', info[7])
            elif 'mode' in info:
                print('mode=', info[5])
            # 与matlab的链接↑



        if timestamp is not None and save_data == True:
            # print(timestamp, sample)
            data = sample[3:7] + sample[13:17]

            percent_data.append(data)
            # print('data: ' + str(data))

            ist1 += 1
            if ist1 == 128:

                ist1 = 0
                percent_data = np.array(percent_data).T
                # print(percent_data.shape)
                seq = dataPreprocess(percent_data)
                # print(percent_data2.shape)
                test_data.append(seq)
                percent_data = []

                ist2 += 1

                if ist2 == 6:
                    ist2 = 0
                    save_data = False   # 只处理前6秒数据
                    # print(test_data)
                    test_data1 = overlap(test_data[:3])     # 滑窗处理，凑齐5个样本
                    test_data2 = overlap(test_data[3:])

                    test_data1 = np.array(data_normal(test_data1))      # 归一化
                    test_data2 = np.array(data_normal(test_data2))

                    test_data1 = torch.tensor(test_data1, dtype=torch.float).permute(0, 2, 1, 3)
                    test_data1 = test_data1.to(device)
                    test_data2 = torch.tensor(test_data2, dtype=torch.float).permute(0, 2, 1, 3)
                    test_data2 = test_data2.to(device)

                    pre1 = model(test_data1)    # 预测前一个编码样本
                    label1 = torch.argmax(pre1, dim=1)
                    pre2 = model(test_data2)    # 预测后一个编码样本
                    label2 = torch.argmax(pre2, dim=1)

                    order1 = []
                    order2 = []
                    length = len(label1)
                    for i in range(length):     # 各个位置的编码由五投票机制决定
                        if label1[i] == 0:
                            order1.append(action2id['空'])
                        elif label1[i] == 1:
                            order1.append(action2id['眼动'])
                        if label2[i] == 0:
                            order2.append(action2id['空'])
                        elif label2[i] == 1:
                            order2.append(action2id['眼动'])

                    test_data = []
                    print('order1: ' + str(order1))
                    print('order2: ' + str(order2))
                    # 输出最终的指令id
                    final_ins = None
                    instructId1 = max(order1, key=order1.count)
                    instructId2 = max(order2, key=order2.count)
                    if instructId1 == 0 and instructId2 == 0:
                        final_ins = 1
                    elif instructId1 == 0 and instructId2 == 1:
                        final_ins = 2
                    elif instructId1 == 1 and instructId2 == 0:
                        final_ins = 3
                    elif instructId1 == 1 and instructId2 == 1:
                        final_ins = 4

                    print('final_ins: ' + str(id2action[final_ins]))

                    # tcp_socket.send(str(instructId).encode('utf-8'))
                    # print(f'cost:{time.time()-start_time:.4f}s')
                    # print('send')
                    # from_server_msg = tcp_socket.recv(200)
                    # 加上.decode("gbk")可以解决乱码
                    # print(from_server_msg.decode("gbk"))
        elif timestamp is None:
            # tcp_socket.close()
            break
