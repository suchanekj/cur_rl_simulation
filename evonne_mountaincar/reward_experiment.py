#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Nov 15 21:11:04 2019

@author: stan

This file runs the cartpole experiment with different reward functions.

For each reward function it measures how many training epochs it takes to solve
the problem. Solving the problem is defined as by OpenAI - 100 consecutive 
trials with average episode length over 195.
"""
import math

def reward_custom(state, rew_idx):
    # Copy the termination conditions from the gym 
    x_threshold = 2.4
    g = 0.0025
    position, velocity = state
    if rew_idx==0:
        return -1.0
    if rew_idx==1:
        # reward based on KE
        # 256/213/148 iterations
        return velocity * velocity
    if rew_idx==2:
        # reward based on time and KE
        # 168/238/211 iterations
        # 10000 is for comparable reward from KE and time
        return 10000 * velocity * velocity - 1 
    if rew_idx==3:
        # reward based on GPE, did not solve in 3 trials of 500 epochs
        return math.sin(3*position)*g/3
    if rew_idx==4:
        # reward based on GPE and KE
        # 338 iterations
        return 0.5*velocity*velocity +math.sin(3*position)*g/3