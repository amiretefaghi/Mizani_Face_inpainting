# -*- coding: utf-8 -*-
"""train.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1XNcu98M0w6T8NYrJBEZAGiwiSZfp4hNn
"""

# !nvidia-smi

# !pip install face-alignment

# !pip install -q kaggle

# !mkdir ~/.kaggle

# !cp /content/drive/MyDrive/Kaggle/kaggle.json ~/.kaggle

# !chmod 600 ~/.kaggle/kaggle.json

# !kaggle datasets download -d lamsimon/celebahq

# !unzip celebahq.zip -d /content/

# %cp -r /content/drive/MyDrive/train_mask.zip /content/

# %cp -r /content/drive/MyDrive/val_mask.zip /content/

# !unzip train_mask.zip -d /content

# !unzip /content/val_mask.zip -d /content

# !mv /content/content/train_mask /content/

# !mv /content/content/val_mask /content/

# %cp -r /content/drive/MyDrive/Mizani-implementation /content/Mizani-implementation

# %cd /content/drive/MyDrive/Mizani-implementation/

from networks import Fine_encoder_g, Coarse_encoder_g, Decoder_g, Discriminator
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras.layers import *
import os
from PIL import Image
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageFile
import argparse
from tqdm import tqdm

import face_alignment
from skimage import io

fa = face_alignment.FaceAlignment(face_alignment.LandmarksType._2D, flip_input=False)

def im_file_to_tensor(img,mask,scatter):
  def _im_file_to_tensor(img,mask,scatter):
    path = f"{img.numpy().decode()}"
    im = Image.open(path)
    im = im.resize((256,256))
    im = np.array(im).astype(float) / 255.0
    path = f"{mask.numpy().decode()}"
    mask = Image.open(path)
    mask = mask.resize((256,256))
    mask = np.array(mask).astype(float) / 255.0
    landmarks = fa.get_landmarks_from_image(im*mask*255.0)
    if landmarks == None:
      landmarks = fa.get_landmarks_from_image(im*255.0)
    indices = tf.constant(landmarks[0],dtype=tf.int32)
    updates = tf.constant([1.0]*landmarks[0].shape[0])
    shape = tf.constant([256,256])
    scatter = tf.scatter_nd(indices, updates, shape)
    scatter = tf.transpose(scatter)
    scatter = tf.expand_dims(scatter,axis=-1)
    return im, mask , scatter
  return tf.py_function(_im_file_to_tensor, 
                        inp=(img,mask,scatter), 
                        Tout=(tf.float32,tf.float32,tf.float32))

def Create_dataset(images_path,masks_path,batch_size = 8):
  f = open(images_path,'r')
  img_paths = f.read()
  img_paths = img_paths.split(sep='\n')
  f = open(masks_path,'r')
  mask_paths = f.read()
  mask_paths = mask_paths.split(sep='\n')
  mask_paths.pop()
  img_paths.pop()

  img_paths = np.array(img_paths)
  mask_paths = np.array(mask_paths)

  indx = np.asarray(range(len(img_paths)))
  np.random.shuffle(indx)
  img_paths = img_paths[indx]
  mask_paths = mask_paths[indx]

  #step 1
  img_names = tf.constant(img_paths)
  mask_names = tf.constant(mask_paths)
  scatter = tf.constant([0]*(len(img_paths)))

  # step 2: create a dataset returning slices of `filenames`
  dataset = tf.data.Dataset.from_tensor_slices((img_names,mask_names,scatter))

  dataset = dataset.map(im_file_to_tensor)
  batch_dataset = dataset.batch(batch_size)

  return batch_dataset

class GAN(tf.keras.Model):
    def __init__(self, image_shape = (256,256),dual=2):
        super(GAN, self).__init__()
        
        if dual == 0:
          self.coarse_size = (image_shape[0],image_shape[1],4)
          self.coarse_encoder = Coarse_encoder_g(self.coarse_size)
        elif dual == 1:
          self.fine_size = (image_shape[0],image_shape[1],3)
          self.fine_encoder = Fine_encoder_g(self.fine_size)
        else:
          self.fine_size = (image_shape[0],image_shape[1],3)
          self.coarse_size = (image_shape[0],image_shape[1],4)
          self.fine_encoder = Fine_encoder_g(self.fine_size)
          self.coarse_encoder = Coarse_encoder_g(self.coarse_size)

        if dual == 2:
          self.decoder = Decoder_g(input_shape=(32,32,512))
        else:
          self.decoder = Decoder_g(input_shape=(32,32,256))

    def fine_encode(self, x):
      return self.fine_encoder(x)
    
    def coarse_encode(self, x):
      return self.coarse_encoder(x)

    def decode(self, f1,f2):
      output = self.decoder([f1,f2])
      return output

def build_networks (image_shape= (256,256) ,continue_training = False, dual=2):
  gan = GAN(image_shape= image_shape,dual)
  discriminator = Discriminator(input_shape=fine_image_shape)

  if continue_training == True:
    if dual == 0:
      gan.coarse_encoder.load_weights(f'./gan/coarse_encoder_latest_weights_dual{dual}.h5')
    elif dual == 1:
      gan.fine_encoder.load_weights(f'./gan/fine_encoder_latest_weights_dual{dual}.h5')
    else:
      gan.fine_encoder.load_weights(f'./gan/fine_encoder_latest_weights_dual{dual}.h5')
      gan.coarse_encoder.load_weights(f'./gan/coarse_encoder_latest_weights_dual{dual}.h5')
    
    gan.decoder.load_weights('./gan/decoder_latest_weights_dual{dual}.h5')
    discriminator.load_weights('./gan/discriminator_latest_weights_dual{dual}.h5')

  return gan, discriminator

def perc_model (vgg_model):
  
  output1 = vgg_model.layers[1].output
  output2 = vgg_model.layers[4].output
  output3 = vgg_model.layers[7].output
  output4 = vgg_model.layers[12].output
  output5 = vgg_model.layers[17].output
  perceptual_model = keras.Model(inputs=vgg_model.input,outputs=[output1,output2,output3,output4,output5])
  return perceptual_model

def gram_matrix(features):
  f_size = [features.shape[0],features.shape[-1],features.shape[1]*features.shape[2]]
  features = tf.reshape(features,f_size)
  result = tf.matmul(features, features, transpose_b=True)
  return result

def perc_style_loss(image: tf.Tensor,
                    output: tf.Tensor,
                    perceptual_model: tf.keras.Model) -> tf.Tensor:
  image_v = keras.applications.vgg19.preprocess_input(image*255.0)
  output_v = keras.applications.vgg19.preprocess_input(output*255.0)
  
  output_f1, output_f2, output_f3, output_f4, output_f5 = perceptual_model(output_v) 
  image_f1, image_f2, image_f3, image_f4, image_f5 = perceptual_model(image_v)

  perc_f1 = tf.reduce_mean(tf.reduce_mean(tf.abs(image_f1-output_f1),axis=(1,2,3)))
  perc_f2 = tf.reduce_mean(tf.reduce_mean(tf.abs(image_f2-output_f2),axis=(1,2,3)))
  perc_f3 = tf.reduce_mean(tf.reduce_mean(tf.abs(image_f3-output_f3),axis=(1,2,3)))
  perc_f4 = tf.reduce_mean(tf.reduce_mean(tf.abs(image_f4-output_f4),axis=(1,2,3)))
  perc_f5 = tf.reduce_mean(tf.reduce_mean(tf.abs(image_f5-output_f5),axis=(1,2,3)))
  perceptual_loss = perc_f1 + perc_f2 + perc_f3 + perc_f4 + perc_f5
  # perceptual_loss /= 5 

  img_gram_f1 = gram_matrix(image_f1)
  out_gram_f1 = gram_matrix(output_f1)
  img_gram_f2 = gram_matrix(image_f2)
  out_gram_f2 = gram_matrix(output_f2)
  img_gram_f3 = gram_matrix(image_f3)
  out_gram_f3 = gram_matrix(output_f3)
  img_gram_f4 = gram_matrix(image_f4)
  out_gram_f4 = gram_matrix(output_f4)
  img_gram_f5 = gram_matrix(image_f5)
  out_gram_f5 = gram_matrix(output_f5)


  ratio = (image_f3.shape[-1]**2)*(image_f3.shape[-1]*(image_f3.shape[1]*image_f3.shape[2])**2)

  style_loss = tf.reduce_mean(tf.reduce_sum(tf.abs(img_gram_f3-out_gram_f3),axis=(1,2))/ratio)

  ratio = (image_f1.shape[-1]**2)*(image_f1.shape[-1]*(image_f1.shape[1]*image_f1.shape[2])**2)

  style_loss += tf.reduce_mean(tf.reduce_sum(tf.abs(img_gram_f1-out_gram_f1),axis=(1,2))/ratio)

  ratio = (image_f2.shape[-1]**2)*(image_f2.shape[-1]*(image_f2.shape[1]*image_f2.shape[2])**2)

  style_loss += tf.reduce_mean(tf.reduce_sum(tf.abs(img_gram_f2-out_gram_f2),axis=(1,2))/ratio)

  ratio = (image_f4.shape[-1]**2)*(image_f4.shape[-1]*(image_f4.shape[1]*image_f4.shape[2])**2)

  style_loss += tf.reduce_mean(tf.reduce_sum(tf.abs(img_gram_f4-out_gram_f4),axis=(1,2))/ratio)

  ratio = (image_f5.shape[-1]**2)*(image_f5.shape[-1]*(image_f5.shape[1]*image_f5.shape[2])**2)

  style_loss += tf.reduce_mean(tf.reduce_sum(tf.abs(img_gram_f5-out_gram_f5),axis=(1,2))/ratio)

  style_loss /= 5 

  return perceptual_loss, style_loss


@tf.function
def train_g (gan: tf.keras.Model,
           discriminator: tf.keras.Model,
           g_opt: tf.keras.optimizers.Optimizer,
           d_opt: tf.keras.optimizers.Optimizer,
           image: tf.Tensor,mask: tf.Tensor,scatter: tf.Tensor,
           epoch: int, pre_epoch: int , dual: int) -> tf.Tensor:
  g_loss = 0
  d_loss = 0
  with tf.GradientTape() as tape1,tf.GradientTape() as tape2:
    input1 = image*mask

    input2 = tf.concat([input1,scatter],-1)

    if dual == 0:
      f = gan.coarse_encoder(input2)
      
    elif dual == 1:
      f = gan.fine_encoder(input1)
    
    elif dual == 2:
      f1 = gan.fine_encoder(input1)
      f2 = gan.coarse_encoder(input2)
      
      f = Concatenate()([f2,f1])

    output = gan.decoder(f)

    l1_loss = tf.reduce_mean(tf.reduce_mean(tf.abs(image-output),axis=(1,2,3)))
    
    perceptual_loss, style_loss = perc_style_loss(image,output,perceptual_model)

    g_loss = l1_loss + 0.1*perceptual_loss  +  250 * style_loss + contrastive_loss
    
    d_fake = discriminator(output)
    adv_g_loss = -tf.reduce_mean(tf.reduce_mean(tf.math.log(tf.squeeze(d_fake)),axis=(1,2)))

    d_real = discriminator(image)

    d_loss_fake = -tf.reduce_mean(tf.reduce_mean(tf.math.log(1.0  - tf.squeeze(d_fake)),axis=(1,2)))
    d_loss_real = -tf.reduce_mean(tf.reduce_mean(tf.math.log(tf.squeeze(d_real)),axis=(1,2)))

    d_loss = d_loss_fake + d_loss_real

    d_g_loss = g_loss + 0.01 * adv_g_loss

  if epoch > pre_epoch:

    d_grads = tape2.gradient(d_loss,discriminator.trainable_weights)
    d_opt.apply_gradients(zip(d_grads,discriminator.trainable_weights))

    g_grads = tape1.gradient(d_g_loss,gan.trainable_weights)
    g_opt.apply_gradients(zip(g_grads,gan.trainable_weights))
  
  else:

    g_grads = tape1.gradient(g_loss,gan.trainable_weights)
    g_opt.apply_gradients(zip(g_grads,gan.trainable_weights))

  return g_loss , d_loss

@tf.function
def train_g_d (gan: tf.keras.Model,
           discriminator: tf.keras.Model,
           g_opt: tf.keras.optimizers.Optimizer,
           d_opt: tf.keras.optimizers.Optimizer,
           image: tf.Tensor,mask: tf.Tensor,scatter: tf.Tensor,
           epoch: int, pre_epoch: int,
           dual: int) -> tf.Tensor:
  g_loss = 0
  d_loss = 0
  with tf.GradientTape() as tape1,tf.GradientTape() as tape2:
    input1 = image*mask

    input2 = tf.concat([input1,scatter],-1)

    if dual == 0:
      f = gan.coarse_encoder(input2)
      
    elif dual == 1:
      f = gan.fine_encoder(input1)
    
    elif dual == 2:
      f1 = gan.fine_encoder(input1)
      f2 = gan.coarse_encoder(input2)
    
      f = Concatenate()([f2,f1])

    output = gan.decoder(f)


    l1_loss = tf.reduce_mean(tf.reduce_mean(tf.abs(image-output),axis=(1,2,3)))
    
    perceptual_loss, style_loss = perc_style_loss(image,output,perceptual_model)

    g_loss = l1_loss + 0.1*perceptual_loss  +  250 * style_loss + contrastive_loss
    
    d_fake = discriminator(output)
    adv_g_loss = -tf.reduce_mean(tf.reduce_mean(tf.math.log(tf.squeeze(d_fake)),axis=(1,2)))

    d_real = discriminator(image)

    d_loss_fake = -tf.reduce_mean(tf.reduce_mean(tf.math.log(1.0  - tf.squeeze(d_fake)),axis=(1,2)))
    d_loss_real = -tf.reduce_mean(tf.reduce_mean(tf.math.log(tf.squeeze(d_real)),axis=(1,2)))

    d_loss = d_loss_fake + d_loss_real

    d_g_loss = g_loss + 0.01 * adv_g_loss

  if epoch > pre_epoch:

    d_grads = tape2.gradient(d_loss,discriminator.trainable_weights)
    d_opt.apply_gradients(zip(d_grads,discriminator.trainable_weights))

    g_grads = tape1.gradient(d_g_loss,gan.trainable_weights)
    g_opt.apply_gradients(zip(g_grads,gan.trainable_weights))
  
  else:

    g_grads = tape1.gradient(g_loss,gan.trainable_weights)
    g_opt.apply_gradients(zip(g_grads,gan.trainable_weights))

  return g_loss , d_loss

def high_pass_x_y(image):
  x_var = image - tf.roll(image,shift=-1,axis=1)
  y_var = image - tf.roll(image,shift=-1,axis=2)

  return x_var, y_var

@tf.function
def validation_batch (gan: tf.keras.Model,
                      img, msk,sc,dual ) -> tf.Tensor:

  input1 = img*msk

  input2 = tf.concat([input1,sc],-1)

  if dual == 0:
    f = gan.coarse_encoder(input2)
    
  elif dual == 1:
    f = gan.fine_encoder(input1)
  
  elif dual == 2:
    f1 = gan.fine_encoder(input1)
    f2 = gan.coarse_encoder(input2)
    
    f = Concatenate()([f2,f1])
  
  output = gan.decoder(f)

  l1_loss = tf.reduce_sum(tf.reduce_mean(tf.abs(img-output),axis=(1,2,3)))
  
  gx , gy = high_pass_x_y(output)
  grad_norm2 = gx**2 + gy**2
  TV = tf.reduce_sum(tf.reduce_mean(tf.sqrt(grad_norm2),axis=(1,2,3)),axis=0)

  mse = tf.reduce_mean((output*255.0 - img*255.0) ** 2,axis=(1,2,3))
  # if mse == 0:
  #     psnr = 100
  # else:
  psnr = 20 * tf.experimental.numpy.log10(255.0 / tf.sqrt(mse))

  PSNR = tf.reduce_sum(psnr,axis=0)

  # out_landmarks = fa.get_landmarks(output[0].numpy()*255.0)
  # img_landmarks = fa.get_landmarks(img[0].numpy()*255.0)
  # if out_landmarks is None:
  #   mse_landmark = np.mean(np.sum((0 - img_landmarks[0])**2,axis=1))
  
  out_dic = {'total_l1_loss': l1_loss,
            'PSNR' : PSNR,
            'TV_loss' : TV}

  return out_dic

def validation (gan: tf.keras.Model,
                val_dataset) -> tf.Tensor:

  total_l1_loss = 0
  TV = 0
  PSNR = 0
  total_size = 0
  for s, (img,msk,sc) in enumerate(val_dataset):
    total_size += img.shape[0]
    out_dic_batch = validation_batch(gan = gan,
                                     img = img, msk = msk,
                                     sc = sc)
    PSNR += out_dic_batch['PSNR']
    TV += out_dic_batch['TV_loss']
    total_l1_loss += out_dic_batch['total_l1_loss']
    
  out_dic = {'total_l1_loss': total_l1_loss.numpy()/total_size,
             'PSNR' : PSNR.numpy()/total_size,
             'TV_loss' : TV.numpy()/total_size}
  return out_dic

if __name__ == '__main__':
  # Instantiate the parser
  parser = argparse.ArgumentParser(description='Optional app description')

  parser.add_argument('--batch_size', type=int, default=8,
                      help='batch size of training and evaluation')
  parser.add_argument('--epochs', type=int, default=120,
                      help='number epochs of training and evaluation')
  parser.add_argument('--pre_epoch', type=int, default=40,
                      help='number epochs without discriminator')
  parser.add_argument('--initial_epoch', type=int, default=1,
                      help='initial_epoch')
  parser.add_argument('--continue_training', action='store_true',
                       help='continue training: load the latest model')

  parser.add_argument('--train_images_path', type=str,
                      help='Path of text file of train images paths')
  parser.add_argument('--train_masks_path', type=str,
                      help='Path of text file of train masks paths')
  parser.add_argument('--val_images_path', type=str,
                      help='Path of text file of val images paths')
  parser.add_argument('--val_masks_path', type=str,
                      help='Path of text file of val images paths')
  parser.add_argument('--dual', type=int, default=2,
                      help='duality of encoder,0 for just coarse encoder,1 for just fine encoder,2 for both of them')

  args = parser.parse_args()

  val_images_path_txt = args.val_images_path
  train_images_path_txt = args.train_images_path
  val_masks_path_txt = args.val_masks_path
  train_masks_path_txt = args.train_masks_path

  fine_image_shape = (256,256,3)
  coarse_image_shape = (256,256,4)
  batch_size = args.batch_size
  val_batch_size = args.batch_size
  epochs = args.epochs
  pre_epoch = args.pre_epoch
  initial_epoch = args.initial_epoch
  continue_training = args.continue_training
  if args.initial_epoch > 1:
    continue_training = True

  dual = args.dual
  g_learning_rate = 1e-4
  d_learning_rate = 5e-5

  train_dataset = Create_dataset(train_images_path_txt,
                                train_masks_path_txt,
                                batch_size = batch_size)
  val_dataset = Create_dataset(val_images_path_txt,
                              val_masks_path_txt,
                              batch_size = val_batch_size)

  gan, discriminator = build_networks(image_shape = (256,256),
                                      continue_training = continue_training,dual=dual)

  vgg19_model = keras.applications.VGG19(include_top=False,input_shape=fine_image_shape)

  g_opt = keras.optimizers.Adam(g_learning_rate)
  d_opt = keras.optimizers.Adam(d_learning_rate)

  perceptual_model = perc_model(vgg19_model)

  val_out_dic = validation(gan = gan,
                          val_dataset = val_dataset)

  print(f'validation loss before start training : {val_out_dic}')

  val_PSNR = [val_out_dic['PSNR']]
  val_L1_loss = [val_out_dic['total_l1_loss']]
  val_TV_loss = [val_out_dic['TV_loss']]

  g_losses = []
  d_losses = []

  for epoch in range(epochs):
    epoch += initial_epoch
    for step, (image,mask,scatter) in tqdm(enumerate(train_dataset)):
      if epoch <= pre_epoch:
        g_loss , d_loss = train_g(gan=gan,discriminator=discriminator,
                                g_opt=g_opt,d_opt=d_opt,
                                image=image,mask=mask,scatter=scatter,
                                epoch=epoch,pre_epoch=pre_epoch,dual=dual)
      else:
        g_loss , d_loss = train_g_d(gan=gan,discriminator=discriminator,
                                    g_opt=g_opt,d_opt=d_opt,
                                    image=image,mask=mask,scatter=scatter,
                                    epoch=epoch,pre_epoch=pre_epoch,dual=dual)        
      if step%100 == 0:
        g_losses.append(g_loss)
        print(f'g loss epoch {epoch} step {step} : {g_loss} ')
        if epoch > pre_epoch:
          d_losses.append(d_loss)
          print(f'd loss epoch {epoch} step {step} : {d_loss} ')

    val_out_dic = validation(gan = gan,
                            val_dataset = val_dataset)
    val_PSNR.append(val_out_dic['PSNR'])
    val_L1_loss.append(val_out_dic['total_l1_loss'])
    val_TV_loss.append(val_out_dic['TV_loss'])
    print(f'validation loss after epoch {epoch} : {val_out_dic}')

    if epoch >= 5 and epoch%5 == 0:
      if dual == 0:
        gan.coarse_encoder.save_weights(f'./gan/coarse_encoder_{epoch}_weights_dual{dual}.h5')
      elif dual == 1:
        gan.fine_encoder.save_weights(f'./gan/fine_encoder_{epoch}_weights_dual{dual}.h5')
      else:
        gan.fine_encoder.save_weights(f'./gan/fine_encoder_{epoch}_weights_dual{dual}.h5')
        gan.coarse_encoder.save_weights(f'./gan/coarse_encoder_{epoch}_weights_dual{dual}.h5')

      gan.decoder.save_weights(f'./gan/decoder_{epoch}_weights_dual{dual}.h5')
      discriminator.save_weights(f'./gan/discriminator_{epoch}_weights_dual{dual}.h5')

    if dual == 0:
      gan.coarse_encoder.save_weights(f'./gan/coarse_encoder_latest_weights_dual{dual}.h5')
    elif dual == 1:
      gan.fine_encoder.save_weights(f'./gan/fine_encoder_latest_weights_dual{dual}.h5')
    else:
      gan.fine_encoder.save_weights(f'./gan/fine_encoder_latest_weights_dual{dual}.h5')
      gan.coarse_encoder.save_weights(f'./gan/coarse_encoder_latest_weights_dual{dual}.h5')

    gan.decoder.save_weights(f'./gan/decoder_latest_weights_dual{dual}.h5')
    discriminator.save_weights(f'./gan/discriminator_latest_weights_dual{dual}.h5')

  np.save('./gan/results/g_losses',np.array(g_losses))
  np.save('./gan/results/d_losses',np.array(d_losses))
  np.save('./gan/results/val_PSNR',np.array(val_PSNR))
  np.save('./gan/results/val_L1_loss',np.array(val_L1_loss))
  np.save('./gan/results/val_TV_loss',np.array(val_TV_loss))