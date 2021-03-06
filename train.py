from transformers import AlbertForMaskedLM,AlbertConfig
from lib.tokenizer import init_tokenizer
from lib.dataset import DURDataset
from torch.utils.data import DataLoader
import torch 
from transformers import AdamW
from sklearn.metrics import accuracy_score
import torch.nn as nn
import os
from lib.tool import split_dataset, stats_bar

def _training_assembly_line(batch_index, batch_dict, model, device, optimizer=None, is_test=False):
    if(is_test):
        model.eval()
    else:
        model.train()
        assert optimizer is not None
    
    #
    batch_dict = [t.to(device) for t in batch_dict]
    outputs = model(
        batch_dict[0],
        token_type_ids = batch_dict[1],
        attention_mask = batch_dict[2],
        labels = batch_dict[3]
        )
    loss,logits = outputs[:2]
    if torch.cuda.device_count()>1:
        loss = loss.mean()
    
    if(is_test == False):
        loss.sum().backward()
        optimizer.step()
        # scheduler.step()  # Update learning rate schedule
    model.zero_grad()

    # compute the loss
    loss_t = loss.item()
    # running_loss_val += (loss_t - running_loss_val) / (batch_index + 1)

    # compute the accuracy
    masked_indexs = torch.argmax(batch_dict[3],dim=1).tolist()
    _predict_ids = torch.argmax(logits,dim=2)
    predict_ids = []
    target_ids = []
    for i,masked_index in enumerate(masked_indexs):
        predict_token_id = _predict_ids[i][masked_index].to('cpu')
        predict_ids.append(predict_token_id)

        target_id = batch_dict[3][i][masked_index].to('cpu')
        target_ids.append(target_id)
    
    acc_t = accuracy_score(target_ids,predict_ids)
    # running_acc += (acc_t - running_acc) / (batch_index + 1)

    return loss_t,acc_t

if __name__ == "__main__":
    batch_size = int(os.environ.get('MODEL_BATCH_SIZE',16))
    tokenizer = init_tokenizer("voidful/albert_chinese_tiny")
    model = AlbertForMaskedLM.from_pretrained("voidful/albert_chinese_base",from_tf=False)
    model.resize_token_embeddings(len(tokenizer))
    full_dataset = DURDataset(tokenizer,'training_dataset/train.data.cht.txt')
    train_dataset, test_dataset = split_dataset(full_dataset,split_rate=0.25)
    train_dataloader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=4)
    test_dataloader = DataLoader(test_dataset, batch_size=int(batch_size/2), shuffle=False)

    # setting device    
    device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')
    if torch.cuda.device_count() > 1:
        print(torch.cuda.device_count(), "GPUs!")
        model = nn.DataParallel(model)
    print("using device",device)
    model.to(device)

    # Prepare optimizer and schedule (linear warmup and decay)
    no_decay = ['bias', 'LayerNorm.weight']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)], 'weight_decay': 0.0},
        {'params': [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
        ]
    optimizer = AdamW(optimizer_grouped_parameters, lr=5e-6, eps=1e-8)
    # scheduler = WarmupLinearSchedule(optimizer, warmup_steps=args.warmup_steps, t_total=t_total)

    #
    model.zero_grad()
    running_loss_val = 0.0
    running_acc = 0.0
    test_running_loss_val = 0.0
    test_running_acc = 0.0

    #
    for epoch in range(3):
        #
        running_loss_val = 0.0
        running_acc = 0.0
        for batch_index, batch_dict in enumerate(train_dataloader):
            loss_t, acc_t = _training_assembly_line(batch_index, batch_dict, \
                model=model, device=device, optimizer=optimizer, is_test= False)
            running_loss_val += (loss_t - running_loss_val) / (batch_index + 1)
            running_acc += (acc_t - running_acc) / (batch_index + 1)
            stats_bar("epoch:%2d batch:%4d train_loss:%2.4f train_acc:%3.4f test_loss:%2.4f test_acc:%3.4f"\
                %(epoch+1, batch_index+1, running_loss_val, running_acc, test_running_loss_val, test_running_acc))
        
        #
        test_running_loss_val = 0.0
        test_running_acc = 0.0
        for batch_index, batch_dict in enumerate(test_dataloader):
            loss_t, acc_t = _training_assembly_line(batch_index, batch_dict, \
                model=model, device=device, is_test= True)
            test_running_loss_val += (loss_t - test_running_loss_val) / (batch_index + 1)
            test_running_acc += (acc_t - test_running_acc) / (batch_index + 1)
            stats_bar("epoch:%2d batch:%4d train_loss:%2.4f train_acc:%3.4f test_loss:%2.4f test_acc:%3.4f"\
                %(epoch+1, batch_index+1, running_loss_val, running_acc, test_running_loss_val, test_running_acc))
            
            