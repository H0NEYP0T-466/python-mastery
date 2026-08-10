#def add_item(item,container=None):
#    if container is None:
#        container=[]
#    container.append(item)
#    return container

#print(add_item(213))
#print(add_item(111))


def find(list,target):
    if list is None:
        return None
    newlist=[]
    for i in list:
        if target==i:
            newlist.append(i)
    return newlist

x=[1,2,3,4,5,1,1,1,1,2]
print(find(x,2))