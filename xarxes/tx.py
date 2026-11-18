import numpy as np
X0=502261.2; K=2000/(1162.26-28.56)
TOP={'a':4647751.0,'b':4646501.0,'c':4645251.0}
def make(L):
    def f(p):
        p=np.asarray(p,float); return np.c_[X0+(p[:,0]-28.56)*K, TOP[L]-(p[:,1]-15.68)*K]
    return f
