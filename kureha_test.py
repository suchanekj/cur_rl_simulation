#this works with tf2.2.0 and python3.8.2 installed
#RL code in main.py from google drive + hand_optimization.py
import sys
import os
from pylab import *
import math
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import gym
import passive_hand_env
from passive_hand_env.passive_hand_env import goal_distance
import tensorflow.compat.v1 as tf
tf.disable_v2_behavior()
#using keras
import tensorflow.keras as keras
from gym.envs.registration import registry, register, make, spec
import numpy as np
from gym import wrappers
from reward_experiment import reward_custom

os.environ["CUDA_VISIBLE_DEVICES"]=""

kwargs = {
    'reward_type': 'sparse',
}
obs = np.zeros((5, 25))
sens_data = np.zeros((5, 4))

class Agent(object):
    # only modification from original RL code is the kind of simulator called from the OpenAI package
    def __init__(self, input_size=13, hidden_size=20, gamma=0.95,
                 action_size=3, lr=0.1, dir='tmp/trial/'):
        register(
            id='PassiveHandLift-v0',
            entry_point='passive_hand_env:PassiveHandLift',
            kwargs=kwargs,
            max_episode_steps=50,
        )
        self.env = gym.make('PassiveHandLift-v0')
        # If you wish to save the simulation video, simply uncomment the line below
        # self.env = wrappers.Monitor(self.env, dir, force=True, video_callable=self.video_callable)

        self.input_size = input_size
        self.hidden_size = hidden_size
        self.gamma = gamma
        self.action_size = action_size
        self.lr = lr
        # save the hyper parameters
        self.params = self.__dict__.copy()

        # inputs to the controller
        self.input_pl = tf.placeholder(tf.float32, [None, input_size])
        self.action_pl = tf.placeholder(tf.int32, [None])
        self.reward_pl = tf.placeholder(tf.float32, [None])

        # Here we use a single layered neural network as controller, which proved to be sufficient enough.
        self.output = keras.layers.Dense(action_size,
                                            #input = self.input_pl,
                                             bias_initializer=None,
                                             activation=tf.nn.softmax)(self.input_pl)

        # responsible output
        self.one_hot = tf.one_hot(self.action_pl, action_size)
        self.responsible_output = tf.reduce_sum(self.output * self.one_hot, axis=1)

        # loss value of the network
        self.loss = -tf.reduce_mean(tf.log(self.responsible_output) * self.reward_pl)

        # get all network variables
        variables = tf.trainable_variables()
        self.variable_pls = []
        for i, var in enumerate(variables):
            self.variable_pls.append(tf.placeholder(tf.float32))

        # compute the gradient values
        self.gradients = tf.gradients(self.loss, variables)

        # update network variables
        solver = tf.train.AdamOptimizer(learning_rate=self.lr)
        # solver = tf.train.MomentumOptimizer(learning_rate=self.lr,momentum=0.95)
        self.update = solver.apply_gradients(zip(self.variable_pls, variables))


    def video_callable(self, episode_id):
        # display the simulation trajectory every 50 epoch
        return episode_id % 50 == 0

    def next_action(self, sess, feed_dict, greedy=False):
        """Pick an action based on the current state.
        Args:
        - sess: a tensorflow session
        - feed_dict: parameter for sess.run()
        - greedy: boolean, whether to take action greedily
        Return:
            Integer, action to be taken.
        """
        ans = sess.run(self.output, feed_dict=feed_dict)[0]
        if greedy:
            return ans.argmax()
        else:
            return np.random.choice(range(self.action_size), p=ans)

    def show_parameters(self):
        """Helper function to show the hyper parameters."""
        for key, value in self.params.items():
            print(key, '=', value)

def discounted_reward(rewards, gamma):
    """Compute the discounted reward."""
    ans = np.zeros_like(rewards)
    running_sum = 0
    # compute the result backward
    for i in reversed(range(len(rewards))):
        running_sum = running_sum * gamma + rewards[i]
        ans[i] = running_sum
    return ans

#modified this code from RL code 
def one_trial(agent, sess, grad_buffer, reward_itr, episode_len_itr, i, render = False):
    '''
    this function does follow things before a trial is done:
    1. get a sequence of actions based on the current state and a given control policy
    2. get the system response of a given action
    3. get the instantaneous reward of this action
    once a trial is done:
    1. get the "long term" value of the controller
    2. get the gradient of the controller
    3. update the controller variables
    4. output the state history
    '''

    # reset the environment
    
    """
    For the mountain car example, the current state, s = agent.env.reset()
    agent.env.rest() returned np.array(self.state), where
        self.state = np.array([self.np_random.uniform(low=-0.6, high=-0.4), 0])
        
    So the starting state for the mountain car was:
    position = uniform random value in [-0.6, -0.4]
    velocity = 0
    
    for the arm, position in cartesian coordinates rather than intrinsic so we can't just set position = 0
    so I defined the state = (distance, height) of cylinder relative to the starting position
        """
    agent.env.reset()
    #starting position stated in hand_optimization.py
    starting_pos = np.array([1.46177789, 0.74909766, 0])
    # defining our state to be (distance, height) relative to starting position
    starting_state = np.array([0]*13)
    s= np.array(starting_state)
    for idx in range(len(grad_buffer)):
        grad_buffer[idx] *= 0
    state_history = []
    reward_history = []
    action_history = []
    current_reward = 0


    while True:

        feed_dict = {agent.input_pl: [s]}
        # update the controller deterministically
        greedy = False
        # get the controller output under a given state
        action = agent.next_action(sess, feed_dict, greedy=greedy)
        # get the next states after taking an action
        
        '''
        agent.env.step(action) returns:
        for the MountainCar: np.array(self.state), reward, done, {}
        for the Hand: obs, reward, done, info
        
        obs['observation']:
            [0:3] - grip_pos
            [3:6] - object_pos
            [6:9] - object_rel_pos
            [9:12] - grip_rot
            [12:15] - object_velp
            [15:18] - object_velr
            [18:21] - grip_velp
            
        obs['achieved_goal']: object position
        obs['desired_goal']: object goal
        '''
        
        obs, r, done, info = agent.env.step(action)
        # working out the state from obs
        object_rel_pos = obs['observation'][6:9]
        grip_rot = obs['observation'][9:12]
        object_velr = obs['observation'][15:18]
        sensor_data = agent.env.sim.data.sensordata
        snext = np.concatenate([object_rel_pos, grip_rot, object_velr, sensor_data])
        if render and i % 50 == 0:
            agent.env.render()
        #using rew_index = 5 instead of 3
        r = reward_custom(s, 5)
        current_reward += r
        state_history.append(s)
        reward_history.append(r)
        action_history.append(action)
        s = snext

        if done:

            # record how long it has been balancing when the simulation is done
            reward_itr += [current_reward]
            print('Max position: ',np.amax([s[0] for s in state_history]))
            print('Reward: ', current_reward)
            episode_len_itr += [len(reward_history)]
            
            # get the "long term" rewards by taking decay parameter gamma into consideration
            rewards = discounted_reward(reward_history, agent.gamma)

            # normalizing the reward makes training faster
            rewards = (rewards - np.mean(rewards)) / np.std(rewards)

            # compute network gradients
            feed_dict = {
                agent.reward_pl: rewards,
                agent.action_pl: action_history,
                agent.input_pl: np.array(state_history)
            }
            episode_gradients = sess.run(agent.gradients,feed_dict=feed_dict)
            for idx, grad in enumerate(episode_gradients):
                grad_buffer[idx] += grad

            # apply gradients to the network variables
            feed_dict = dict(zip(agent.variable_pls, grad_buffer))
            sess.run(agent.update, feed_dict=feed_dict)

            # reset the buffer to zero
            for idx in range(len(grad_buffer)):
                grad_buffer[idx] *= 0
            break

    return state_history

def animate_itr(i,*args):
    '''animantion of each training epoch'''
    agent, sess, grad_buffer, reward_itr, episode_len_itr, sess, grad_buffer, agent, obt_itr, render = args
    #
    state_history = one_trial(agent, sess, grad_buffer, reward_itr, episode_len_itr, i, render)
    xlist = [range(len(reward_itr))]
    ylist = [reward_itr]
    
    if episode_len_itr[-1]<200:
        print('Solved in {} iterations'.format(len(reward_itr)))
        input('Press to continue')
    
    for lnum, line in enumerate(lines_itr):
        line.set_data(xlist[lnum], ylist[lnum])  # set data for each line separately.

    if len(reward_itr) % obt_itr == 0:
        x_mag = 1.2
        y_mag = 0.07
        # normalize to (-1,1)
        xlist = [np.asarray(state_history)[:,0] / x_mag]
        ylist = [np.asarray(state_history)[:,1] / y_mag]
        lines_obt.set_data(xlist, ylist)
        tau = 0.02
        time_text_obt.set_text('physical time = %6.2fs' % (len(xlist[0])*tau))

    return (lines_itr,) + (lines_obt,) + (time_text_obt,)


def get_fig(max_epoch):
    fig = plt.figure()
    ax_itr = axes([0.1, 0.1, 0.8, 0.8])
    ax_obt = axes([0.5, 0.2, .3, .3])

    # able to display multiple lines if needed
    global lines_obt, lines_itr, time_text_obt
    lines_itr = []
    lobj = ax_itr.plot([], [], lw=1, color="blue")[0]
    lines_itr.append(lobj)
    lines_obt = []

    ax_itr.set_xlim([0, max_epoch])
    ax_itr.set_ylim([-2.0, 2.0])#([min_reward, 0])
    ax_itr.grid(False)
    ax_itr.set_xlabel('trainig epoch')
    ax_itr.set_ylabel('reward')

    time_text_obt = []
    ax_obt.set_xlim([-1, 1])
    ax_obt.set_ylim([-1, 1])
    ax_obt.set_xlabel('cart position (normalised)')
    ax_obt.set_ylabel('cart velocity (normalised)')
    lines_obt = ax_obt.plot([], [], lw=1, color="red")[0]
    time_text_obt = ax_obt.text(0.05, 0.9, '', fontsize=13, transform=ax_obt.transAxes)
    return fig, ax_itr, ax_obt, time_text_obt

"""
def measure_time_to_solve(args):
    exp_results = [] 
    global reward_itr
    for exp_idx in range(10):
        i=0
        agent, sess, grad_buffer, reward_itr, sess, grad_buffer, agent, obt_itr, render = args
        reward_itr = []
        while True:
            state_history = one_trial(agent, sess, grad_buffer, reward_itr, i, render)
            i+=1
            #xlist = [range(len(reward_itr))]
            #ylist = [reward_itr]
            print(len(reward_itr))
            if len(reward_itr)>100:
                avg_reward_past_100 = np.mean(reward_itr[-100:])
                if avg_reward_past_100 >= 195.0:
                    print('Solved in {} iterations'.format(len(reward_itr)))
                    print(reward_itr)
                    break
        exp_results.append(len(reward_itr))
    return np.mean(exp_results)
"""

def main():
    obt_itr = 10
    max_epoch = 3000
    # whether to show the pole balancing animation
    render = True
    dir = 'tmp/trial/'

    # set up figure for animation
    fig, ax_itr, ax_obt, time_text_obt = get_fig(max_epoch)
    agent = Agent(hidden_size=24, lr=0.2, gamma=0.95, dir=dir)
    agent.show_parameters()

    # tensorflow initialization for neural network controller
    tfconfig = tf.ConfigProto()
    tfconfig.gpu_options.allow_growth=True
    sess = tf.Session(config=tfconfig)
    tf.global_variables_initializer().run(session=sess)
    grad_buffer = sess.run(tf.trainable_variables())
    tf.reset_default_graph()

    global reward_itr, episode_len_itr
    reward_itr = []
    episode_len_itr = []
    args = [agent, sess, grad_buffer, reward_itr, episode_len_itr, sess, grad_buffer, agent, obt_itr, render]
    # run the experiment 10 times and find average number of iterations
    # required to solve
    #measure_time_to_solve(args)
    # run the optimization and output animation
    ani = animation.FuncAnimation(fig, animate_itr,fargs=args)
    plt.show()

if __name__ == "__main__":
   main()

# Set up formatting for the movie files
# print('saving animation...')
# Writer = animation.writers['ffmpeg']
# writer = Writer(fps=100, metadata=dict(artist='Me'), bitrate=1800)
